"""Which interface the player uses: "legacy" (the game's own menus) or "new"
(the companion app, icserver/webapp.py).

2026-10-16 16:58 (tester): the first start shows the legacy interface; each
interface has a way to switch to the other one (the client says it will
restart, then opens in the other interface); Play / Launch start the tutorial
in both; after a match the chosen interface comes back.

- The choice is kept in data/progress.json ("interface"); `python ic.py play`
  opens it ([app] default_interface for the first start).
- New -> legacy: the app's Settings. The app closes and the game opens (or comes
  to the front if it is already running).
- Legacy -> new: the hotkey [app] switch_hotkey (Ctrl+Shift+U) while the game
  runs. A confirmation box says the game will close; then the app opens. A
  button inside the game's own Options menu would mean editing the game's Flash
  UI files, which is not done yet.
- After a match, in the new interface, the game window is minimized and the app
  comes to the front ([app] return_to_app_after_match).
"""
import threading
import time

from . import log, progress, winctl

MODES = ("legacy", "new")


def mode(cfg):
    m = progress.get(cfg, "interface")
    return m if m in MODES else (cfg["app"].get("default_interface", "legacy") or "legacy")


def set_mode(cfg, m):
    if m not in MODES:
        raise ValueError(f"unknown interface {m!r}")
    progress.put(cfg, "interface", m)
    log.info(f"interface: {m}")


class Switcher:
    """Set up by ic.py (it knows how to start the game and open the app)."""

    def __init__(self, server, launch_client=None, open_app=None):
        self.server = server
        self.cfg = server.cfg
        self.launch_client = launch_client
        self.open_app = open_app
        self.exe = self.cfg["game"]["patched_exe"]
        self.busy = threading.Lock()

    # ---- helpers ----------------------------------------------------------------------
    def game_running(self):
        return bool(winctl.pids_of(self.exe)) or any(not s.user.closed for s in self.server.sessions)

    def _later(self, delay, fn):
        def run():
            time.sleep(delay)
            try:
                fn()
            except Exception as e:                       # noqa: BLE001
                log.info(f"interface: {e!r}")
        threading.Thread(target=run, name="interface", daemon=True).start()

    # ---- switches ---------------------------------------------------------------------
    def to_legacy(self):
        """From the app's Settings: the app closes, the game opens in its own menus."""
        set_mode(self.cfg, "legacy")

        def go():
            winctl.close(winctl.app_windows())
            if winctl.pids_of(self.exe):
                winctl.focus(winctl.game_windows(self.exe))
            elif self.launch_client:
                self.launch_client()
        self._later(1.2, go)            # let the app show its message first
        return {"ok": True, "game_running": self.game_running()}

    def to_new(self, ask=True):
        """From the game (hotkey): confirm, close the game, open the app."""
        if not self.busy.acquire(blocking=False):
            return False
        try:
            game = winctl.game_windows(self.exe)
            winctl.minimize(game)          # a fullscreen game could hide the box
            if ask and not winctl.confirm(
                    "Infinite Crisis",
                    "Switch to the new interface?\n\nThe game will close and Infinite Crisis will restart in the "
                    "new launcher. Press Play there to start a match."):
                winctl.focus(game)
                return False
            set_mode(self.cfg, "new")
            if winctl.pids_of(self.exe):
                winctl.kill(self.exe)
            if self.open_app:
                self.open_app()
            return True
        finally:
            self.busy.release()

    def toggle(self):
        """The hotkey: legacy -> new; in the new interface it brings the app forward."""
        if mode(self.cfg) == "legacy":
            self.to_new()
        else:
            if not winctl.focus(winctl.app_windows()) and self.open_app:
                self.open_app()

    # ---- match flow -------------------------------------------------------------------
    def before_match(self):
        """The app queued a match: the game window comes to the front."""
        self._later(0.2, lambda: winctl.focus(winctl.game_windows(self.exe)))

    def after_match(self):
        """A match ended: in the new interface the app comes back."""
        if mode(self.cfg) != "new" or not self.cfg["app"].get("return_to_app_after_match", True):
            return

        def go():
            winctl.minimize(winctl.game_windows(self.exe))
            if not winctl.focus(winctl.app_windows()) and self.open_app:
                self.open_app()
        self._later(self.cfg["app"].get("return_to_app_delay", 2.0), go)
