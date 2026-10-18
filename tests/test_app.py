"""The companion app (fase3-ft): its HTTP routes, the Play button,
friends and chat (fase3-fw).

  1. Play with no game open -> the server remembers the encounter; the next
     login is queued for it by itself (JoinQueue answers arrive unasked).
  2. Play while the game sits in the menus -> queued at once.

    python tests/test_app.py tests/e2e.example.toml
"""
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_e2e as T                       # noqa: E402
from icserver import config as config_mod, log   # noqa: E402
from icserver.server import Server         # noqa: E402


def http(cfg, path, body=None):
    url = f"http://127.0.0.1:{cfg['server']['soap_port']}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=10) as r:
        raw = r.read()
        return r.status, (json.loads(raw) if r.headers.get("Content-Type", "").startswith("application/json") else raw)


def main(cfg_path):
    cfg = config_mod.load(cfg_path)
    log.setup(cfg.log_dir, cfg["debug"]["hexdump"])
    server = Server(cfg)
    server.start()
    launched = []
    server.launch_client = lambda: launched.append(time.monotonic())

    status, page = http(cfg, "/app")
    T.check("GET /app serves the page", status == 200 and b"<title>" in page)
    status, st = http(cfg, "/api/state")
    T.check("GET /api/state", status == 200 and "player" in st and st["online"] is False, st)
    status, champs = http(cfg, "/api/champions")
    T.check("GET /api/champions", status == 200 and len(champs) >= 40, len(champs))
    status, items = http(cfg, "/api/items")
    T.check("GET /api/items", status == 200 and items["amplifiers"] and items["artifacts"])
    status, enc = http(cfg, "/api/encounters")
    T.check("GET /api/encounters has a playable one", any(e["playable"] for e in enc))

    # friends and chat (fase3-fw)
    import tempfile
    server.webapp.social.path = os.path.join(tempfile.mkdtemp(), "social.json")
    server.webapp.social.data = server.webapp.social._load()
    status, r = http(cfg, "/api/social/friend", {"me": "Player", "name": "Diana"})
    T.check("add a friend", r.get("ok"), r)
    status, r = http(cfg, "/api/social/friend", {"me": "Player", "name": "player"})
    T.check("adding yourself is refused", r.get("ok") is False, r)
    http(cfg, "/api/social?me=Diana")
    status, ov = http(cfg, "/api/social?me=Player")
    T.check("friend shows online", ov["friends"] and ov["friends"][0]["status"] == "online", ov)
    status, r = http(cfg, "/api/chat", {"me": "Diana", "to": "Player", "text": "hi"})
    T.check("send a chat message", r.get("ok"), r)
    status, ov = http(cfg, "/api/social?me=Player")
    T.check("unread count", ov["friends"][0]["unread"] == 1, ov)
    status, msgs = http(cfg, "/api/chat?me=Player&with=Diana")
    T.check("read the conversation", [m["text"] for m in msgs["messages"]] == ["hi"], msgs)
    status, ov = http(cfg, "/api/social?me=Player")
    T.check("read clears unread", ov["friends"][0]["unread"] == 0, ov)

    status, r = http(cfg, "/api/play", {"encounter": "0x40000A81"})
    T.check("Play on a stage that isn't ready is refused", r.get("ok") is False, r)

    status, r = http(cfg, "/api/play", {"encounter": "0x40000991"})
    T.check("Play with no game open launches it", r.get("ok") and r.get("launched") and launched, r)
    T.check("encounter remembered for the login", server.pending_queue == 0x40000991)

    t0 = time.monotonic()
    u = T.login_and_menu(cfg, server)
    delay = cfg["app"].get("queue_after_login_delay", 1.5)
    T.check("queued by itself after the login",
            u.wait_for(lambda e: e[0] >= t0 and e[2] == 0x20FA, delay + 3.0))
    sess = server.sessions[-1]
    T.check("session QUEUED", sess.phase == "QUEUED", sess.phase)
    T.check("pending encounter cleared", not server.pending_queue)

    # back to the menus, then Play from the app while the game is open
    with sess.lock:
        sess.match = None
        sess.set_phase("MENU")
    t1 = time.monotonic()
    status, r = http(cfg, "/api/play", {"encounter": "0x40000991"})
    T.check("Play while in the menus queues at once", r.get("queued") is True, r)
    T.check("JoinQueue answers sent", u.wait_for(lambda e: e[0] >= t1 and e[2] == 0x20FA, 2.0))

    # interface switch (fase3-fx)
    from icserver import interface, progress
    progress.put(cfg, "interface", None)
    T.check("first start: legacy interface", interface.mode(cfg) == "legacy", interface.mode(cfg))
    launched2, opened = [], []
    server.switcher = interface.Switcher(server, lambda: launched2.append(1), lambda: opened.append(1))
    status, ui = http(cfg, "/api/interface")
    T.check("GET /api/interface", ui.get("mode") == "legacy" and ui.get("can_switch"), ui)
    interface.set_mode(cfg, "new")
    status, r = http(cfg, "/api/interface", {"mode": "legacy"})
    T.check("switch to legacy from the app", r.get("ok") and interface.mode(cfg) == "legacy", r)
    T.check("switching with the game open does not start a second game", not launched2 or not r.get("game_running"))
    T.check("hotkey switch to new (no confirmation)", server.switcher.to_new(ask=False) and interface.mode(cfg) == "new"
            and opened)
    calls = []
    server.switcher.after_match = lambda: calls.append(1)
    sess.finished_match = True
    u.send_event(T.SVC, 0x20C4, b"")
    time.sleep(1.0)
    T.check("end page closed after a match -> the chosen interface comes back", calls == [1], calls)
    u.send_event(T.SVC, 0x20C4, b"")
    time.sleep(0.3)
    T.check("Launch (0x20C4 without a match) does not", calls == [1], calls)
    progress.put(cfg, "interface", None)

    log.flush()
    failed = [n for n, ok in T.CHECKS if not ok]
    print(f"{len(T.CHECKS) - len(failed)}/{len(T.CHECKS)} checks passed")
    if failed:
        print("FAILED:", failed)
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "e2e.example.toml"))
