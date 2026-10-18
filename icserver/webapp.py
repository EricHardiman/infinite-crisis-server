"""The companion app ("the new interface"): a local web app served by the
server's HTTP port (the SOAP port, 8888 by default) at /app.

2026-10-16 15:59 (tester): redesign the whole interface, modern and clean, for
everything; the in-game menus stay as "Legacy". First version: home / play,
profile and cosmetics, champions and skins, amplifiers / artifacts / Stolen
Powers. Pictures come from the player's own install (/tex/<did>.png,
icserver/textures.py); the data from the server's roster, the catalog tables
and data/progress.json.

Routes
  GET  /app, /app/...        the page (icserver/webui/)
  GET  /api/state            account, progress, server status, pending launch
  GET  /api/champions        the roster (data/champions.json + roster.py) with skills
  GET  /api/cosmetics        avatar icons (+ the header slots)
  GET  /api/items            amplifiers, artifacts, Stolen Powers
  GET  /api/encounters       what can be played
  POST /api/profile/icon     {"slot": 0-4, "icon": did}
  POST /api/play             {"encounter": did}: launch the game, queue after login
  GET  /tex/<did>.png?s=256  a game texture as PNG
"""
import csv
import json
import os
import re
import threading
import time

from . import log, progress

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBUI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webui")
DATA = os.path.join(ROOT, "catalog", "data")
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
                 ".json": "application/json"}
PLAYABLE = {0x40000991}


def _tsv(name):
    path = os.path.join(DATA, name)
    try:
        with open(path, encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f, delimiter="\t"))
    except OSError:
        return []
    if not rows:
        return []
    head = rows[0]
    return [dict(zip(head, r)) for r in rows[1:] if r]


def _hx(v):
    return f"0x{int(v):08X}" if isinstance(v, int) and v else ""


def _did(text):
    try:
        return int(str(text).split(":")[0], 16)
    except (TypeError, ValueError):
        return 0


_cache = {}


def _cached(key, fn):
    if key not in _cache:
        _cache[key] = fn()
    return _cache[key]


class WebApp:
    def __init__(self, server):
        self.server = server
        self.cfg = server.cfg
        self.lock = threading.Lock()
        from .social import Social
        self.social = Social(server.cfg)

    # ---- data ---------------------------------------------------------------------
    def state(self):
        cfg = self.cfg
        sessions = [s for s in self.server.sessions if not s.user.closed]
        done = progress.completed(cfg)
        return {
            "player": cfg["account"].get("player_name", "Player"),
            "level": cfg["account"].get("level", 30),
            "completed": [_hx(d) for d in done],
            "profile_icons": [_hx(i) for i in (self._header_icons())],
            "online": bool(sessions),
            "phase": sessions[-1].phase if sessions else "",
            "pending": _hx(getattr(self.server, "pending_queue", 0) or 0),
            "champions": len(self.server.roster),
            "time": time.time(),
        }

    def _in_game(self):
        return any(not s.user.closed for s in self.server.sessions)

    def _header_icons(self):
        saved = progress.profile_icons(self.cfg)
        if saved is not None:
            return saved
        from . import messages as M
        return [wc for wc, ctype in M.EXTRA_OWNABLES if ctype == 3][:5]

    def champions(self):
        def build():
            skills = {}
            for r in _tsv("skills.tsv"):
                skills.setdefault(r.get("champion", ""), []).append({
                    "slot": r.get("slot", ""), "key": r.get("key", ""), "name": r.get("name", ""),
                    "icon": r.get("icon", ""), "stats": r.get("stats", ""), "status": r.get("server_status", "")})
            from . import messages as M
            playable = {"Gaslight Batman"}
            out = []
            for c in self.server.roster:
                costumes = [{"variant": _hx(s.get("variant")), "wallpaper": _hx(s.get("wallpaper")),
                             "portrait": _hx(s.get("grid_icon"))} for s in M.costumes(c)]
                out.append({"name": c["name"], "id": _hx(c.get("id")), "variant": _hx(c.get("variant")),
                            "portrait": _hx(c.get("grid_icon")), "art": _hx(c.get("tex799")),
                            "wallpaper": _hx(c.get("wallpaper")), "skins": costumes,
                            "skills": sorted(skills.get(c["name"], []), key=lambda s: s["slot"]),
                            "new": c.get("added_by") == "roster.py", "unreleased": bool(c.get("unreleased")),
                            "playable": c["name"] in playable})
            return sorted(out, key=lambda c: c["name"])
        return _cached("champions", build)

    def cosmetics(self):
        return {"icons": [{"id": r["id"], "picture": r.get("picture", ""), "name": r.get("name", "")}
                          for r in _tsv("avatar_icons.tsv")],
                "header": [_hx(i) for i in self._header_icons()]}

    def items(self):
        def build():
            return {
                "amplifiers": [{"id": r["id"], "name": r.get("name", ""), "type": r.get("type", ""),
                                "brand": r.get("brand", ""), "stats": r.get("stats", ""),
                                "targets": r.get("targets", "")} for r in _tsv("amplifiers.tsv")],
                "artifacts": [{"id": r["id"], "name": r.get("name", ""), "category": r.get("category", ""),
                               "tier": r.get("tier", ""), "cost": r.get("cost", ""), "icon": r.get("icon", ""),
                               "stats": r.get("stats", "")} for r in _tsv("artifacts.tsv")],
                "stolen_powers": [{"id": r["id"], "power": r.get("power", ""), "champion": r.get("champion", ""),
                                   "icon": r.get("icon", "")} for r in _tsv("stolen_powers.tsv")],
            }
        return _cached("items", build)

    def encounters(self):
        out = []
        for r in _tsv("stages.tsv"):
            did = _did(r["id"])
            out.append({"id": r["id"], "name": r.get("name", ""), "mode": r.get("mode", ""),
                        "playable": did in PLAYABLE, "notes": r.get("notes", "")})
        from . import messages as M
        for did, name in M.ENCOUNTERS:
            if not any(_did(e["id"]) == did for e in out):
                out.append({"id": _hx(did), "name": name, "mode": "Training" if "Tutorial" in name else "Match",
                            "playable": did in PLAYABLE, "notes": ""})
        return out

    # ---- actions --------------------------------------------------------------------
    def set_icon(self, body):
        slot, icon = int(body.get("slot", 0)), _did(body.get("icon", 0))
        icons = progress.set_profile_icon(self.cfg, slot, icon)
        log.info(f"app: profile icon {icon:#x} in header slot {slot}")
        from . import scorecard
        for s in [s for s in self.server.sessions if not s.user.closed]:
            with s.lock:
                s.send(f"protector icon slot (0x2154) from the app: {icon:#x} -> {slot}",
                       scorecard.protector_icon_slot(icon, slot))
        return {"ok": True, "header": [_hx(i) for i in icons]}

    def play(self, body):
        did = _did(body.get("encounter", "0x40000991")) or 0x40000991
        if did not in PLAYABLE:
            return {"ok": False, "error": "not playable yet"}
        self.server.pending_queue = did
        live = [s for s in self.server.sessions if not s.user.closed]
        if live and live[-1].phase == "MENU":
            self.server.pending_queue = 0
            with live[-1].lock:
                live[-1].queue_now(did, "the app's Play button")
            sw = getattr(self.server, "switcher", None)
            if sw:
                sw.before_match()
            return {"ok": True, "launched": False, "queued": True}
        launched = False
        if not live and self.cfg["app"].get("launch_game", True):
            launcher = getattr(self.server, "launch_client", None)
            if launcher:
                launcher()
                launched = True
        log.info(f"app: play {did:#x} ({'game launched, ' if launched else ''}queued after the login)")
        return {"ok": True, "launched": launched, "queued": False}

    def interface(self):
        from . import interface
        sw = getattr(self.server, "switcher", None)
        return {"mode": interface.mode(self.cfg), "hotkey": self.cfg["app"].get("switch_hotkey", ""),
                "can_switch": sw is not None, "return_after_match": self.cfg["app"].get("return_to_app_after_match", True)}

    def set_interface(self, body):
        from . import interface
        m = body.get("mode")
        sw = getattr(self.server, "switcher", None)
        if m == "legacy" and sw:
            return sw.to_legacy()
        interface.set_mode(self.cfg, m)
        return {"ok": True}

    # ---- HTTP ---------------------------------------------------------------------------
    def handles(self, path):
        return path == "/" or path.startswith(("/app", "/api/", "/tex/"))

    def serve(self, handler, method, path, body):
        route = path.split("?", 1)[0]
        if route in ("/", "/app"):
            return self._file(handler, "index.html")
        if route.startswith("/app/"):
            return self._file(handler, route[5:])
        if route.startswith("/tex/"):
            return self._texture(handler, path)
        api = {"/api/interface": self.interface, "/api/state": self.state, "/api/champions": self.champions, "/api/cosmetics": self.cosmetics,
               "/api/items": self.items, "/api/encounters": self.encounters}
        posts = {"/api/profile/icon": self.set_icon, "/api/play": self.play, "/api/interface": self.set_interface,
                 "/api/social/friend": lambda d: self.social.friend(d.get("me"), d.get("name"), bool(d.get("remove"))),
                 "/api/chat": lambda d: self.social.send(d.get("me"), d.get("to"), d.get("text"))}
        from urllib.parse import parse_qs
        q = {k: v[0] for k, v in parse_qs(path.split("?", 1)[1] if "?" in path else "").items()}
        api["/api/social"] = lambda: self.social.overview(q.get("me"), q.get("status"), self._in_game())
        api["/api/chat"] = lambda: self.social.messages(q.get("me"), q.get("with"), int(q.get("since") or 0))
        try:
            if method == "POST" and route in posts:
                data = json.loads(body or b"{}")
                return self._json(handler, posts[route](data))
            if route in api:
                return self._json(handler, api[route]())
        except Exception as e:                          # noqa: BLE001
            log.info(f"app: {route}: {e!r}")
            return self._json(handler, {"ok": False, "error": str(e)}, 500)
        return self._send(handler, 404, b"not found", "text/plain")

    def _texture(self, handler, path):
        m = re.match(r"/tex/(?:0x)?([0-9a-fA-F]{8})\.png(?:\?s=(\d+))?", path)
        if not m:
            return self._send(handler, 404, b"", "text/plain")
        from . import textures
        did, size = int(m.group(1), 16), int(m.group(2) or 0)
        png = textures.png_path(os.path.join(self.cfg.game_dir, "rp"), did, size)
        if not png:
            return self._send(handler, 404, b"", "text/plain")
        with open(png, "rb") as f:
            return self._send(handler, 200, f.read(), "image/png", cache=True)

    def _file(self, handler, rel):
        path = os.path.normpath(os.path.join(WEBUI, rel))
        if not path.startswith(WEBUI) or not os.path.isfile(path):
            return self._send(handler, 404, b"not found", "text/plain")
        with open(path, "rb") as f:
            data = f.read()
        return self._send(handler, 200, data, CONTENT_TYPES.get(os.path.splitext(path)[1], "application/octet-stream"))

    def _json(self, handler, obj, status=200):
        return self._send(handler, status, json.dumps(obj).encode(), "application/json")

    @staticmethod
    def _send(handler, status, data, ctype, cache=False):
        handler.send_response(status)
        handler.send_header("Content-Type", ctype)
        handler.send_header("Content-Length", str(len(data)))
        handler.send_header("Cache-Control", "max-age=86400" if cache else "no-store")
        handler.end_headers()
        if handler.command != "HEAD":
            handler.wfile.write(data)
