"""Small Windows helpers for switching between the two interfaces (the game's
own menus = "legacy", the companion app = "new"): find, minimize, restore and
close windows, stop the game client, a native confirmation box and a global
hotkey. Everything is a no-op (returns False / None) on other systems or when a
call fails, so the server never stops because of it.
"""
import ctypes
import os
import subprocess
import threading

WINDOWS = os.name == "nt"
APP_TITLE = "Infinite Crisis Launcher"      # <title> of icserver/webui/index.html

if WINDOWS:
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

SW_MINIMIZE, SW_RESTORE = 6, 9
WM_CLOSE, WM_HOTKEY = 0x0010, 0x0312
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x4000
MB_YESNO, MB_ICONQUESTION, MB_TOPMOST, MB_SETFOREGROUND, IDYES = 0x4, 0x20, 0x40000, 0x10000, 6


def _windows():
    """[(hwnd, pid, title)] of the visible top-level windows."""
    out = []
    if not WINDOWS:
        return out

    def cb(hwnd, _l):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            out.append((hwnd, pid.value, buf.value))
        return True
    try:
        user32.EnumWindows(EnumProc(cb), 0)
    except OSError:
        pass
    return out


def pids_of(image):
    """PIDs of the running processes named `image` (e.g. the patched game exe)."""
    if not WINDOWS:
        return []
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=10,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    pids = []
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[0].lower() == image.lower() and parts[1].isdigit():
            pids.append(int(parts[1]))
    return pids


def game_windows(image):
    pids = set(pids_of(image))
    return [w[0] for w in _windows() if w[1] in pids and w[2]]


def app_windows():
    return [w[0] for w in _windows() if w[2].startswith(APP_TITLE)]


def minimize(hwnds):
    for h in hwnds:
        try:
            user32.ShowWindow(h, SW_MINIMIZE)
        except OSError:
            pass
    return bool(hwnds)


def focus(hwnds):
    """Restore and bring to the front (Windows may only flash the taskbar button
    when another program has the focus)."""
    for h in hwnds[:1]:
        try:
            user32.ShowWindow(h, SW_RESTORE)
            user32.keybd_event(0x12, 0, 0, 0)          # a tap on Alt lets SetForegroundWindow work
            user32.keybd_event(0x12, 0, 2, 0)
            user32.SetForegroundWindow(h)
        except OSError:
            pass
    return bool(hwnds)


def close(hwnds):
    for h in hwnds:
        try:
            user32.PostMessageW(h, WM_CLOSE, 0, 0)
        except OSError:
            pass
    return bool(hwnds)


def kill(image):
    if not WINDOWS:
        return False
    try:
        subprocess.run(["taskkill", "/IM", image, "/F"], capture_output=True, timeout=15,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def confirm(title, text):
    """A native Yes / No box on top of everything; True for Yes."""
    if not WINDOWS:
        return False
    try:
        return user32.MessageBoxW(0, text, title, MB_YESNO | MB_ICONQUESTION | MB_TOPMOST | MB_SETFOREGROUND) == IDYES
    except OSError:
        return False


def parse_hotkey(text):
    """"ctrl+shift+u" -> (modifiers, virtual key) or None."""
    mods, vk = MOD_NOREPEAT, None
    for part in str(text or "").lower().replace(" ", "").split("+"):
        if part in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif part == "shift":
            mods |= MOD_SHIFT
        elif part == "alt":
            mods |= MOD_ALT
        elif len(part) == 1 and part.isalnum():
            vk = ord(part.upper())
        elif part.startswith("f") and part[1:].isdigit() and 1 <= int(part[1:]) <= 24:
            vk = 0x6F + int(part[1:])
    return (mods, vk) if vk else None


def hotkey(text, callback):
    """Call callback() (on the hotkey's own thread) whenever the global hotkey is
    pressed. Returns the thread, or None if it could not be registered."""
    if not WINDOWS:
        return None
    parsed = parse_hotkey(text)
    if not parsed:
        return None
    ready, ok = threading.Event(), []

    def run():
        if not user32.RegisterHotKey(None, 1, parsed[0], parsed[1]):
            ready.set()
            return
        ok.append(True)
        ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                try:
                    callback()
                except Exception:                    # noqa: BLE001 -- never kill the hotkey thread
                    pass
    t = threading.Thread(target=run, name="hotkey", daemon=True)
    t.start()
    ready.wait(2.0)
    return t if ok else None


# ---- keyboard watcher (emotes) --------------------------------------------------------
WH_KEYBOARD_LL, WM_KEYDOWN, WM_SYSKEYDOWN, VK_CONTROL = 13, 0x0100, 0x0104, 0x11


def press_key(vk, hold=0.08):
    """A key press (down + up) sent to the window in front (2026-10-17: the throw's aim on F).
    False on other systems or when it fails."""
    if not WINDOWS:
        return False
    # 2026-10-17 21:53 (tester: no aim rings; log: F "pressed" but the client sent nothing): a key with
    # scan code 0 released at once is not seen by the game's input; the press now carries the key's
    # scan code and is held hold s (released on a timer, the server thread is not blocked)
    try:
        scan = user32.MapVirtualKeyW(int(vk), 0) & 0xFF
        user32.keybd_event(int(vk), scan, 0, 0)
    except OSError:
        return False

    def up():
        try:
            user32.keybd_event(int(vk), scan, 2, 0)
        except OSError:
            pass
    t = threading.Timer(max(0.0, float(hold)), up)
    t.daemon = True
    t.start()
    return True


def foreground_pid():
    if not WINDOWS:
        return 0
    try:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(pid))
        return pid.value
    except OSError:
        return 0


def watch_keys(keys, callback):
    """Watch (never swallow) key presses system-wide: callback(vk, ctrl) runs on a
    worker thread for every press of a virtual key in `keys`. The hook itself
    only queues the press, so typing in other programs is never slowed down."""
    if not WINDOWS:
        return None
    import queue
    q = queue.Queue()
    keys = set(keys)
    ready, ok = threading.Event(), []
    LRESULT = ctypes.c_ssize_t
    HookProc = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
    user32.CallNextHookEx.restype = LRESULT
    user32.CallNextHookEx.argtypes = (wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
    user32.SetWindowsHookExW.restype = wintypes.HHOOK
    user32.SetWindowsHookExW.argtypes = (ctypes.c_int, HookProc, wintypes.HINSTANCE, wintypes.DWORD)

    def proc(n, w, l):
        try:
            if n == 0 and w in (WM_KEYDOWN, WM_SYSKEYDOWN):
                vk = ctypes.cast(l, ctypes.POINTER(wintypes.DWORD))[0]
                if vk in keys:
                    q.put((vk, bool(user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)))
        except Exception:                            # noqa: BLE001 -- a hook must never fail
            pass
        return user32.CallNextHookEx(None, n, w, l)
    cb = HookProc(proc)

    def run():
        hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, cb, None, 0)
        if not hook:
            ready.set()
            return
        ok.append(cb)                                # keep the callback alive
        ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            pass

    def work():
        while True:
            vk, ctrl = q.get()
            try:
                callback(vk, ctrl)
            except Exception:                        # noqa: BLE001
                pass
    threading.Thread(target=run, name="keyhook", daemon=True).start()
    threading.Thread(target=work, name="keys", daemon=True).start()
    ready.wait(2.0)
    return bool(ok)
