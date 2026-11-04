"""Listeners: SOAP login (HTTP), user server (TCP + UDP log), game server (TCP)."""
import http.server
import re
import socket
import threading
import time
import traceback
from xml.sax.saxutils import escape

from . import log
from . import script_runtime
from .crypto import load_key
from .gamedata import Data
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
        self.data = Data(cfg.game_dir)
        self.data.missile_scripts_past_starts = bool(cfg["ics"].get("missile_scripts_past_starts", True))
        self.data.record_start_only = bool(cfg["ics"].get("record_start_only", True))
        self.data.template_window_bounded = bool(cfg["ics"].get("template_window_bounded", True))
        self.data.class_scripts = {int(str(k), 0): [int(str(x), 0) for x in v]
                                   for k, v in (cfg["ics"].get("spawned_class_scripts") or {}).items()}
        from . import gamedata as _G
        _G.STOLEN_STAT_MERGE = bool(cfg["ics"].get("stolen_stat_merge", True))
        from . import messages as _M
        _M.DESCRIPTOR_WS_ZERO[0] = bool(cfg["ics"].get("descriptor_world_state_zero", True))
        from . import script_runtime as _R
        _R.ANY_NO_REENTER = bool(cfg["ics"].get("polled_any_no_reenter", True))
        _R.MISSILE_OWN_RETURN_EVENT = bool(cfg["ics"].get("missile_own_return_event", True))
        _R.CAST_WAITS_TETHER = float(cfg["ics"].get("cast_waits_tether", 4.0) or 0.0)
        _R.OWNER_BLOCK = bool(cfg["ics"].get("script_owner_block", True))
        if cfg["ics"].get("graph_cast_timing", True):
            import os as _os
            _path = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "data", "skill_hooks.tsv")
            _R.GRAPH_EXIT_FALLBACK = float(cfg["ics"].get("graph_exit_fallback", 3.0) or 3.0)
            n = _R.load_graph_hooks(_path)
            print(f"graph cast timings: {n} skill scripts" + ("" if n else " (run python tools/graph_hooks.py)"))
        _R.SPEND_BY_VITAL = bool(cfg["ics"].get("spend_by_vital", True))
        _R.SKILL_USED_BROADCAST = bool(cfg["ics"].get("skill_used_broadcast", True))
        _R.SKILL_USED_BROADCAST_TAKEN = bool(cfg["ics"].get("skill_used_broadcast_taken", True))
        _R.TETHER_RETURN = bool(cfg["ics"].get("tether_return", True))
        _R.TETHER_RETRACT = bool(cfg["ics"].get("tether_retract", True))
        _R.TETHER_RETURN_UNLIMITED = bool(cfg["ics"].get("tether_return_unlimited", True))
        _R.STATS_REINIT = bool(cfg["ics"].get("stats_reinit_skills", True))
        _R.HOOKS_ATTACK_SPEED = bool(cfg["ics"].get("hooks_attack_speed", True))
        _R.EVENT_LOOP_LIMIT = int(cfg["ics"].get("event_loop_limit", 4) or 0)
        _R.STATUS_STACK_MODEL = bool(cfg["ics"].get("status_stack_model", True))
        _R.POLL_ONCE_PER_TICK = bool(cfg["ics"].get("script_poll_once_per_tick", True))
        from . import messages as _M
        _M.CHAMPION_DATA_MATCH_PACK[0] = bool(cfg["ics"].get("champion_data_match_pack", True))
        _M.CHAMPION_DATA_COSTUME_ICON[0] = bool(cfg["ics"].get("champion_data_costume_icon", True))
        _R.LOCAL_Y_FORWARD = bool(cfg["ics"].get("local_y_forward", True))
        _R.RESET_LOCALS = bool(cfg["ics"].get("reset_state_locals", True))
        _R.EXIT_REENTRY_GUARD = bool(cfg["ics"].get("exit_chain_reentry_guard", True))
        _R.STOP_LEFT_SUBGRAPHS = bool(cfg["ics"].get("stop_left_subgraphs", True))
        _R.GRAPH_ENTER_FIRST = bool(cfg["ics"].get("graph_enter_before_children", True))
        _R.STATUS_RECORD_FLAGS = bool(cfg["ics"].get("status_record_flags", True))
        _R.LOCAL_FRAMES = bool(cfg["ics"].get("local_frames", True))
        _R.SLOT_COOLDOWN_VARS = bool(cfg["ics"].get("slot_cooldown_vars", True))
        _R.HEADING_FROM_VECTOR = bool(cfg["ics"].get("heading_from_vector", True))
        _R.GRAPH_DONE_WAITS = bool(cfg["ics"].get("graph_done_waits", True))
        _R.LAUNCH_SETS_TARGET = bool(cfg["ics"].get("spawn_event_after_chain", True))
        _R.HANDLE_RUNS = bool(cfg["ics"].get("scriptlet_handle_runs", True))
        _R.SKILL_ECHO_NODE = bool(cfg["ics"].get("skill_echo_node", True))
        _R.SKILL_USED_EVERY_USE = bool(cfg["ics"].get("skill_used_every_use", True))
        _R.STATUS_TIMER_FIRST_WAIT = {int(str(d), 0) for d in (cfg["ics"].get("status_timer_first_wait") or ())}
        # 2026-10-30 tester report 15:30 (agl-r-impact-q-e.md 3.2)
        _R.MISSILE_DESTROY_DELAY_SCRIPTS = {int(str(d), 0)
                                            for d in (cfg["ics"].get("missile_destroy_delay_scripts") or ())}
        # 2026-10-28 15:00 (tester report 2026-10-28 15:00; meltdown-moving-target.md 6)
        _R.REAIM_FROM_CURRENT = bool(cfg["ics"].get("missile_reaim_from_current", True))
        _R.STATUS_ACTS_FOR_SOURCE = bool(cfg["ics"].get("status_acts_for_source", True))
        _R.EVENT_LOOP_PER_TARGET = bool(cfg["ics"].get("event_loop_per_target", True))
        _R.GRAPH_HOOK_OFFSET = float(cfg["ics"].get("graph_hook_offset", 0.13) or 0.0)
        _R.KEEP_COSMETIC_TAIL = float(cfg["ics"].get("keep_cosmetic_tail", 0.8) or 0.0)
        _R.GRAPH_RUNTIME = bool(cfg["ics"].get("graph_runtime", False))
        _R.GRAPH_START_GRACE = float(cfg["ics"].get("graph_start_grace", 0.15) or 0.0)
        _R.GRAPH_COSMETIC_TAIL = bool(cfg["ics"].get("graph_cosmetic_tail", True))
        _R.START_SCRIPTLET_HOLD = {int(str(d), 0) for d in (cfg["ics"].get("start_scriptlet_hold") or ())}
        _R.GRAPH_MISSILE_RELEASE = float(cfg["ics"].get("graph_missile_release", 0.5) or 0.0)
        _R.ACCEPT_FILTER = bool(cfg["ics"].get("script_accept_filter", True))
        _R.DEFER_HOOKS_IN_CHAIN = bool(cfg["ics"].get("defer_graph_hooks_in_chain", True))
        _R.POLL_GUARD_EVENT_RESET = bool(cfg["ics"].get("poll_guard_event_reset", True))
        _R.EXIT_UPDATE = bool(cfg["ics"].get("update_before_event_exit", True))
        _R.EXPIRE_LINGER = float(cfg["ics"].get("missile_expire_linger", 5.0) or 0.0)
        _R.INT_COMPARE_32 = bool(cfg["ics"].get("int_compare_32bit", True))
        _R.TOP_GRAPH_CHAINS = bool(cfg["ics"].get("top_graph_chains", True))
        from . import combat as _CB
        _CB.BOX_CENTERED = bool(cfg["ics"].get("hotspot_box_centered", True))
        if not cfg["ics"].get("raise_event_float_param", True):
            _R.RAISE_PARAMS = _R.RAISE_PARAMS_OLD
        from . import graph as _GR
        _GR.CLIP_SECONDS = float(cfg["ics"].get("graph_clip_seconds", 0.5) or 0.5)
        _GR.COSMETIC_HOLD = float(cfg["ics"].get("graph_cosmetic_hold", 0.8) or 0.0)
        _GR.STATE_TIMEOUT = float(cfg["ics"].get("graph_state_timeout", 5.0) or 0.0)
        _GR.FAST_FORWARD = bool(cfg["ics"].get("graph_fast_forward", True))
        _GR.EARLY_OUT = bool(cfg["ics"].get("graph_lua_early_out", True))
        _GR.SELF_DEBOUNCE = float(cfg["ics"].get("graph_self_debounce", 0.05) or 0.0)
        if _R.GRAPH_RUNTIME:
            print(f"graph runtime: {len(_GR.data())} champion variants" + ("" if len(_GR.data()) else
                                                                          " (run python tools/skill_graphs.py)"))
        _R.TETHER_DRAG = bool(cfg["ics"].get("tether_drag", True))
        _R.CARRIED_ARRIVE_COLLISION = bool(cfg["ics"].get("carried_arrive_collision", True))
        from . import script_nodes as _N
        _N.OWNER_DAMAGED_EVENT[0] = bool(cfg["ics"].get("owner_damaged_event", True))
        _N.DAMAGE_PIPELINE_EVENTS[0] = bool(cfg["ics"].get("damage_pipeline_events", True))
        _N.HOTSPOT_STATUS_DURATION[0] = bool(cfg["ics"].get("hotspot_status_duration", True))
        _R.PREDICATE_FIRST = bool(cfg["ics"].get("predicate_first_in_conditions", True))
        _R.REENTER_ON_CODE = bool(cfg["ics"].get("any_reenter_on_code", False))
        if not self.data.roster:
            raise RuntimeError("data\\champions.json not found (the champion list for the account screens): "
                               "run python tools\\roster.py")
        script_runtime.SCRIPT_RESOLVER = self.data.entity_scripts
        script_runtime.STATUS_RESOLVER = self.data.status_script
        script_runtime.STACKS_RESOLVER = self.data.status_max_stacks
        self.sessions = []
        self.lock = threading.Lock()
        self._waiting_game = None

    def expect_game(self, session):
        with self.lock:
            self._waiting_game = session

    def _session_for_game(self):
        with self.lock:
            s = self._waiting_game
            if s and not s.user.closed:
                return s
            live = [x for x in self.sessions if not x.user.closed]
            return ([x for x in live if x.phase == REFERRED] or live or [None])[-1]

    # ---- SOAP ------------------------------------------------------------------------------
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
        # errorString must be ABSENT on success (rva 0x69b952)
        s = self.cfg["server"]
        fields = [("loginTicket", "1001"), ("randomID", "1"), ("sessionKey", "LOCALSESSIONKEY0001"),
                  ("userServerAddr", s["host"]), ("userServerPort", str(s["user_port"]))]
        inner = "".join(f"<{k}>{escape(v)}</{k}>" for k, v in fields)
        store = self.store_url()
        if store:
            # 2026-10-28 (store-amplifiers.md): nameValuePairs follow loginTicket in the response's field order
            pairs = "".join(f"<nameValuePairs><name>{escape(k)}</name><value>{escape(v)}</value></nameValuePairs>"
                            for k, v in [("URL.Store", store)])
            if self.cfg["ics"].get("auth_pairs_nested", True):
                # 2026-10-28 15:00 (tester report 2026-10-28 15:00: SHOP showed chrome://version; store-fix.md 2.3, C):
                # the member nameValuePairs is a NameValuePairArray (0xADE4F0 +0x18 -> 0xADE2D0) whose items are child
                # elements named nameValuePairs, so the pairs nest one level ([ics] auth_pairs_nested)
                pairs = f"<nameValuePairs>{pairs}</nameValuePairs>"
            inner = inner.replace("</loginTicket>", "</loginTicket>" + pairs, 1)
        return ('<ns2:AuthSelectResponse xmlns:ns2="http://webloginapp.wbnet.turbine.com/">'
                f"<return>{inner}</return></ns2:AuthSelectResponse>")

    def store_url(self):
        """[ics] store_url: "" = this server's store page (ics/store_web.py), "none" = no URL.Store pair."""
        ic, s = self.cfg["ics"], self.cfg["server"]
        url = str(ic.get("store_url", "") or "")
        if url.lower() == "none":
            return ""
        if not url and ic.get("store_web_page", True):
            url = f"http://{s['host']}:{s['soap_port']}/store"
        return url

    def _soap_handler(self):
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _handle(self):
                if self.path.startswith("/store") and server.cfg["ics"].get("store_web_page", True):
                    from . import store_web
                    if not self.path.startswith("/store/img/"):        # pictures: one per card, not logged
                        log.info(f"store page: {self.command} {self.path}")
                    if store_web.handle(server, self):
                        return
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                match = re.search(rb"<(?:[\w.-]+:)?Body[^>]*>\s*<(?:[\w.-]+:)?(\w+)", body)
                op = match.group(1).decode() if match else None
                builder = {"getLauncherData": server.launcher_data, "AuthSelect": server.auth_select}.get(op)
                if op:
                    log.info(f"SOAP {op} {'handled' if builder else 'NOT HANDLED'}")
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

    # ---- TCP -------------------------------------------------------------------------------
    def _serve(self, sock, addr, kind):
        conn = Conn(sock, kind)
        if kind == "user":
            session = Session(self, conn)
            with self.lock:
                self.sessions = [s for s in self.sessions if not s.user.closed] + [session]
            log.info(f"login connection from {addr[0]}:{addr[1]} -> session {session.sid}")
            on_data, on_close = session.on_user_data, session.on_user_closed
        else:
            session = self._session_for_game()
            if session is None:
                log.info("game connection but nobody is logged in; closing")
                conn.close()
                return
            session.attach_game(conn)
            log.info(f"game connection from {addr[0]}:{addr[1]}", session)
            on_data, on_close = session.on_game_data, lambda: session.on_game_closed(conn)
        try:
            while True:
                data = sock.recv(65536)
                if not data:
                    break
                on_data(data)
        except OSError as e:
            log.info(f"{kind} connection error: {e}", session)
        except Exception as e:                       # a bug must not kill the listener
            log.info(f"INTERNAL ERROR ({kind}): {e!r}\n{traceback.format_exc()}", session)
        finally:
            conn.close()
            on_close()

    def _listen(self, srv, kind):
        while True:
            sock, addr = srv.accept()
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            threading.Thread(target=self._serve, args=(sock, addr, kind), daemon=True).start()

    def _udp_log(self, port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((self.cfg["server"]["host"], port))
        while True:
            data, addr = sock.recvfrom(65536)
            log.traffic("udp <<", f"from {addr}", data)

    def _warm_up(self):
        t = time.time()
        self.data.index()
        log.info(f"game data index ready ({len(self.data.index())} records, {time.time() - t:.1f} s)")
        for did in self.cfg["ics"]["encounters"]:
            t = time.time()
            info = self.data.encounter(int(did, 16))
            self.data.prepare(info, self.flow_classes(int(did, 16)))
            log.info(f"encounter {did}: map pack {info['map_pack']:#x}, packs "
                     f"{' '.join(hex(p) for p in info['packs'])} ({time.time() - t:.1f} s)")

    def flow_classes(self, encounter):
        """The classes the encounter's flow (ics/encounters) creates, for Data.prepare."""
        import importlib
        from . import director
        name = str((self.cfg.encounter(encounter) or {}).get("director", "") or "")
        if not name:
            return []
        try:
            return director.flow_classes(importlib.import_module(f"ics.encounters.{name}"), self.cfg["ics"])
        except ImportError:
            return []

    def start(self):
        s = self.cfg["server"]
        http_srv = http.server.ThreadingHTTPServer((s["host"], s["soap_port"]), self._soap_handler())
        user_srv = socket.create_server((s["host"], s["user_port"]))
        game_srv = socket.create_server((s["host"], s["game_port"]))
        for target, args in ((self._listen, (user_srv, "user")), (self._listen, (game_srv, "game")),
                             (self._udp_log, (s["user_port"],)), (http_srv.serve_forever, ()),
                             (self._warm_up, ())):
            threading.Thread(target=target, args=args, daemon=True).start()
        time.sleep(0.2)
        log.info(f"new server (ics) listening on {s['host']}: login {s['soap_port']}, user {s['user_port']}, "
                 f"game {s['game_port']}")
        return http_srv
