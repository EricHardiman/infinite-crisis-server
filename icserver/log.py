"""Three logs in logs\\:
  server.log     what happened, one line per step (read this first)
  traffic.log    every message in and out, with hex dumps (debug.hexdump)
  unhandled.log  client events the server does not answer yet -- this is
                 where new features start (e.g. click the skill-rank button
                 and look here for the event it sends).
"""
import atexit
import collections
import datetime
import os
import queue
import threading
import time

from .wire import hexdump

_lock = threading.Lock()
_dir = None
_hexdump = True
# 2026-10-16 14:02 (tester): after the tutorial's overview movie the Launch
# screen stayed up ~4 s. traffic.log showed ~150 ms between consecutive lines,
# even two lines of the same message: every line opened, appended to and
# closed the file, and printed to the console. Lines now go through a queue to
# one FILE writer thread that keeps the files open (flushed at least every
# 0.5 s), so logging never blocks the network threads. A traffic.log over
# TRAFFIC_ROTATE_MB is renamed to traffic.old.log at server start.
# 2026-10-16 14:41 (tester): with the console printed by that same thread the
# logs stopped right after the start (14:31: nothing after "props:"): on the
# tester's machine the console is so slow (~250 ms a line) that the writer fell
# behind for good and everything queued was lost when the window closed. The
# CONSOLE now has its own thread and only keeps the latest CONSOLE_BACKLOG
# lines (the files always get every line).
_queue = queue.Queue()
_files = {}
_writer = None
_console = collections.deque()
_console_event = threading.Event()
_console_thread = None
_console_dropped = 0
CONSOLE_BACKLOG = 40
TRAFFIC_ROTATE_MB = 32


def setup(log_dir, with_hexdump=True):
    global _dir, _hexdump, _writer, _console_thread
    os.makedirs(log_dir, exist_ok=True)
    _dir, _hexdump = log_dir, with_hexdump
    big = os.path.join(log_dir, "traffic.log")
    try:
        if os.path.getsize(big) > TRAFFIC_ROTATE_MB * 1024 * 1024:
            old = os.path.join(log_dir, "traffic.old.log")
            if os.path.exists(old):
                os.remove(old)
            os.replace(big, old)
    except OSError:
        pass
    if _writer is None:
        _writer = threading.Thread(target=_run, name="log-writer", daemon=True)
        _writer.start()
        _console_thread = threading.Thread(target=_run_console, name="log-console", daemon=True)
        _console_thread.start()
        atexit.register(flush)
    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    for name in ("server.log", "traffic.log", "unhandled.log"):
        _write(name, f"\n===== server start {stamp} =====")


def _flush_files():
    for g in _files.values():
        try:
            g.flush()
        except OSError:
            pass


def _run():
    last_flush = time.monotonic()
    while True:
        try:
            item = _queue.get(timeout=0.5)
        except queue.Empty:
            with _lock:
                _flush_files()
            last_flush = time.monotonic()
            continue
        try:
            log_dir, name, text = item
            with _lock:
                f = _files.get((log_dir, name))
                if f is None:
                    f = _files[(log_dir, name)] = open(os.path.join(log_dir, name), "a", encoding="utf-8")
                f.write(text + "\n")
                if _queue.empty() or time.monotonic() - last_flush > 0.5:
                    _flush_files()
                    last_flush = time.monotonic()
        except (OSError, ValueError):
            pass
        finally:
            _queue.task_done()


def _run_console():
    global _console_dropped
    while True:
        _console_event.wait()
        while True:
            with _lock:
                if not _console:
                    _console_event.clear()
                    break
                line = _console.popleft()
                dropped, _console_dropped = _console_dropped, 0
            try:
                if dropped:
                    print(f"... ({dropped} lines not shown here: see logs\\server.log)", flush=True)
                print(line, flush=True)
            except (OSError, ValueError):
                pass


def _to_console(line):
    global _console_dropped
    if _console_thread is None:
        print(line, flush=True)
        return
    with _lock:
        _console.append(line)
        while len(_console) > CONSOLE_BACKLOG:
            _console.popleft()
            _console_dropped += 1
    _console_event.set()


def flush():
    """Wait until every queued line is in the files (tests, shutdown)."""
    if _writer is not None:
        _queue.join()
    with _lock:
        _flush_files()


def _write(name, text):
    if _dir is None:
        return
    _queue.put((_dir, name, text))


def _now():
    return datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]


def info(text, session=None):
    tag = f"[s{session.sid} {session.phase}] " if session is not None else ""
    line = f"{_now()} {tag}{text}"
    # on Windows a print can block (a slow console, or text selected in it):
    # never from the network threads (2026-10-16 14:23 / 14:41)
    _to_console(line)
    _write("server.log", line)


def traffic(direction, label, data=b"", session=None):
    tag = f"s{session.sid} " if session is not None else ""
    line = f"{_now()} {tag}{direction} {label} ({len(data)} bytes)"
    if _hexdump and data:
        line += "\n" + hexdump(data)
    _write("traffic.log", line)


def unhandled(msg, session=None):
    tag = f"s{session.sid} {session.phase} " if session is not None else ""
    _write("unhandled.log", f"{_now()} {tag}event {msg.event_id:#06x} dest {msg.dest:#018x} "
                            f"flags {msg.flags:#x} body {msg.body.hex()}")
