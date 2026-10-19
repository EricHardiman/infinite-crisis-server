"""Listeners: SOAP login (HTTP), user server (TCP + UDP log), game server (TCP)."""
import http.server
import json
import re
import socket
import threading
import time
from xml.sax.saxutils import escape

from . import log
from .crypto import load_key
from .net import Conn
from .scheduler import Scheduler
from .session import REFERRED, Session

SOAP_ENVELOPE = ('<?xml version="1.0" encoding="utf-8"?>'
                 '<S:Envelope xmlns:S="http://schemas.xmlsoap.org/soap/envelope/">'
                 "<S:Body>{body}</S:Body></S:Envelope>")


class Server:
    def __init__(self, cfg):
        self.cfg = cfg
        self.sched = Scheduler()
        self.key = load_key(cfg.key_path)
        path = cfg.champions_path()
        if not path:
            raise RuntimeError("champions.json not found (put it in data\\ or set server.champions_json)")
        with open(path, encoding="utf-8") as f:
            self.roster = json.load(f)
        # 2026-10-16 15:44 (tester): the install's champions missing from
        # champions.json (Zod, Huntress, Raven...) are added (icserver/roster.py,
        # [account] extra_champions)
        from . import roster as _roster
        try:
            self.roster = _roster.extend(cfg, self.roster, log.info)
        except Exception as e:          # noqa: BLE001 -- never stop the server for this
            log.info(f"extra champions: {e!r}")
        # 2026-10-16 14:02 (tester): unlock the profile's cosmetics (the
        # Protector / avatar icons). [account] unlock_avatar_icons
        from . import cosmetics, messages, log as _log
        messages.EXTRA_OWNABLES[:] = cosmetics.ownables(cfg, _log.info)
        messages.SKIP_BASE_COSTUMES = cfg["account"].get("skip_base_costumes", True)
        self.sessions = []
        self.lock = threading.Lock()
        from .webapp import WebApp
        self.webapp = WebApp(self)
        self.pending_queue = 0         # encounter the app's Play button queues after the next login
        self.launch_client = None      # set by ic.py: starts the game client
        self._waiting_game = None

    # ---- lookups -------------------------------------------------------------------
    def champion_info(self, variant):
        for c in self.roster:
            if c["variant"] == variant:
                return {"name": c["name"], "icon": c.get("tex384", 0)}
            for s in c.get("costume_info", []):
                if s["variant"] == variant:
                    return {"name": c["name"], "icon": c.get("tex384", 0)}
        return {"name": "Champion", "icon": 0}

    def expect_game(self, session):
        """The next game connection belongs to this session (it was just referred)."""
        with self.lock:
            self._waiting_game = session

    def _session_for_game(self):
        with self.lock:
            s = self._waiting_game
            if s and not s.user.closed:
                return s
            live = [x for x in self.sessions if not x.user.closed]
            referred = [x for x in live if x.phase == REFERRED]
            return (referred or live or [None])[-1]

    # ---- SOAP ----------------------------------------------------------------------
    def launcher_data(self):
        s, g = self.cfg["server"], self.cfg["game"]
        data = {
            "Launcher.SupportedLocaleList": g["language"],
            "Patch.Disable": "true",
            "Patch.Regions": f"{g['region']}|http://{s['host']}",
            "GameClient.Filename": g["patched_exe"],
            "ClientLauncher.Filename": "turbineclientlauncher.exe",
            "GameClient.ArgTemplate": ("/e {CLIENTEXE} /n {LANGUAGE} // --loginurl {LOGINURL} "
                                       "--loginregion {REGION} --reportingurl {REPORTINGURL} --language {LANGUAGE}"),
            "URL.Help": f"http://{s['host']}",
            "URL.Register": f"http://{s['host']}",
        }
        pairs = "".join(f"<nameValuePairs><name>{escape(k)}</name><value>{escape(v)}</value></nameValuePairs>"
                        for k, v in data.items())
        return ('<ns2:getLauncherDataResponse xmlns:ns2="http://webloginapp.wbnet.turbine.com/">'
                f"<return>{pairs}</return></ns2:getLauncherDataResponse>")

    def auth_select(self):
        # errorString must be ABSENT on success (rva 0x69b952).
        s = self.cfg["server"]
        fields = [("loginTicket", "1001"), ("randomID", "1"), ("sessionKey", "LOCALSESSIONKEY0001"),
                  ("userServerAddr", s["host"]), ("userServerPort", str(s["user_port"]))]
        inner = "".join(f"<{k}>{escape(v)}</{k}>" for k, v in fields)
        return ('<ns2:AuthSelectResponse xmlns:ns2="http://webloginapp.wbnet.turbine.com/">'
                f"<return>{inner}</return></ns2:AuthSelectResponse>")

    def _soap_handler(self):
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                # the companion app (/app, /api/, /tex/: icserver/webapp.py)
                if server.webapp.handles(self.path):
                    return server.webapp.serve(self, self.command, self.path, body)
                match = re.search(rb"<(?:[\w.-]+:)?Body[^>]*>\s*<(?:[\w.-]+:)?(\w+)", body)
                op = match.group(1).decode() if match else None
                builder = {"getLauncherData": server.launcher_data, "AuthSelect": server.auth_select}.get(op)
                user = re.search(rb"<(?:\w+:)?userName>([^<]*)<", body)
                if op == "AuthSelect":
                    log.info(f"SOAP login for user {user.group(1).decode(errors='replace') if user else '?'}")
                elif op:
                    log.info(f"SOAP {op} {'handled' if builder else 'NOT HANDLED'} ({self.path})")
                log.traffic("soap <<", f"{self.command} {self.path} op={op}", body)
                payload = SOAP_ENVELOPE.format(body=builder() if builder else "").encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/xml; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = do_POST = do_HEAD = _handle

            def log_message(self, fmt, *args):
                pass

        return Handler

    # ---- TCP -------------------------------------------------------------------------
    def _serve_user(self, sock, addr):
        conn = Conn(sock, "user")
        session = Session(self, conn)
        with self.lock:
            self.sessions = [s for s in self.sessions if not s.user.closed] + [session]
        log.info(f"login connection from {addr[0]}:{addr[1]} -> session {session.sid}")
        try:
            while True:
                data = sock.recv(65536)
                if not data:
                    break
                session.on_user_data(data)
        except OSError as e:
            log.info(f"login connection error: {e}", session)
        except Exception as e:                       # a bug must not kill the listener
            log.info(f"INTERNAL ERROR in session: {e!r}", session)
            import traceback
            traceback.print_exc()
        finally:
            conn.close()
            session.on_user_closed()

    def _serve_game(self, sock, addr):
        conn = Conn(sock, "game")
        session = self._session_for_game()
        if session is None:
            log.info(f"game connection from {addr[0]}:{addr[1]} but nobody is logged in; closing")
            conn.close()
            return
        session.attach_game(conn)
        log.info(f"game connection from {addr[0]}:{addr[1]}", session)
        try:
            while True:
                data = sock.recv(65536)
                if not data:
                    break
                session.on_game_data(data)
        except OSError as e:
            log.info(f"game connection error: {e}", session)
        except Exception as e:
            log.info(f"INTERNAL ERROR in game connection: {e!r}", session)
            import traceback
            traceback.print_exc()
        finally:
            conn.close()
            session.on_game_closed(conn)

    def _listen(self, srv, target):
        while True:
            sock, addr = srv.accept()
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            threading.Thread(target=target, args=(sock, addr), daemon=True).start()

    def _udp_log(self, port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((self.cfg["server"]["host"], port))
        while True:
            data, addr = sock.recvfrom(65536)
            log.traffic("udp <<", f"from {addr}", data)

    def _resolve_props(self):
        from . import tutorial1
        try:
            tutorial1.resolve_prop_classes(self.cfg, log=log.info)
        except Exception as e:      # noqa: BLE001 -- never take the server down for this
            log.info(f"props: could not look up the entities ({e})")

    def start(self):
        """Bind everything (raises OSError if a port is taken) and serve in threads."""
        from . import messages as _M
        _M.VITALS_FIRST_LIST = bool(self.cfg["match"].get("vitals_first_list", False))
        s = self.cfg["server"]
        http_srv = http.server.ThreadingHTTPServer((s["host"], s["soap_port"]), self._soap_handler())
        # Bind the TCP ports here so a port already in use fails immediately.
        user_srv = socket.create_server((s["host"], s["user_port"]))
        game_srv = socket.create_server((s["host"], s["game_port"]))
        # 2026-10-16 14:23: before the ports open, not in a background thread
        # during the match (80 s of pack reading starved the network threads:
        # freezes, "server disconnected"). Cached in data/game_cache.json.
        log.info("reading the game data (first start: up to a minute, please wait for 'listening on'; later starts use the cache)")
        self._resolve_props()
        threading.Thread(target=self._listen, args=(user_srv, self._serve_user), daemon=True).start()
        threading.Thread(target=self._listen, args=(game_srv, self._serve_game), daemon=True).start()
        threading.Thread(target=self._udp_log, args=(s["user_port"],), daemon=True).start()
        threading.Thread(target=http_srv.serve_forever, daemon=True).start()
        time.sleep(0.2)
        log.info(f"listening on {s['host']}: login {s['soap_port']}, user {s['user_port']}, game {s['game_port']}")
        return http_srv
