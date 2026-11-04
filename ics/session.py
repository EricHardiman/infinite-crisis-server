"""One login session: account screens, queue, lobby (champion select), loading, the match and its end.

The message order of the load is the one the client needs (worked out in the earlier server, see
docs/reverse-engineering.md): JoinQueue 0x20EB -> AcceptMatch 0x20CA -> referral to the game port -> game hello
-> ConnectToLobby 0x20F2 -> objects once the client loads -> load-complete notice -> playing.

2026-10-22 (docs/re-notes/full-protocol.md 4, full-account-social.md): the account is persistent (ics/account.py),
vs-AI / PvP encounters get a champion select with bots (ics/lobby.py) and hand the map to the mode layer (ics/match,
when it exists), the end of a match gives XP / Merits / achievements and goes back to the menu; the account screens
(amplifier sets, boutique, profile icons, achievements, standings, leaderboards, chat, custom match) are answered.

Several client events carry two names in the notes (full-protocol.md vs full-account-social.md; the conflicts list
of full-index.md). Their handlers decide by context (a custom-match room open, the lobby open, the body) and log
which meaning was taken.
"""
import importlib
import math
import os
import struct
import threading
import time
import traceback

from . import account as A
from . import chat
from . import log
from . import matchend
from . import messages as M
from .crypto import find_session_key_blob
from .lobby import CustomMatch, Lobby, is_lobby_encounter, launch_times
from .scheduler import Group
from .wire import FrameReader, pack_compact, parse_client_position, read_compact
from .world import World
from . import director as D
from .shop import Shop

CONNECTED, MENU, QUEUED, REFERRED, GAME_CONNECTED, LOBBY, LOADING, PLAYING = (
    "CONNECTED", "MENU", "QUEUED", "REFERRED", "GAME_CONNECTED", "LOBBY", "LOADING", "PLAYING")
MATCH_PHASES = (REFERRED, GAME_CONNECTED, LOBBY, LOADING, PLAYING)
NOTICE_LOAD_COMPLETE = bytes.fromhex("5e010010")     # notice 0x1000015e
NOTICE_CINEMATIC = bytes.fromhex("17010010")         # notice 0x10000117: u32 state | u32 cinematic (4 = ended)
NOTICE_SURRENDER = bytes.fromhex("54040010")         # notice 0x10000454: u8 yes / no (surrender vote)
CMD_ATTACK, CMD_ATTACK_MOVE, CMD_MOVE, CMD_STOP, CMD_SKILL = 2, 3, 4, 6, 9
CMD_USE = 1                     # 2026-10-25 16:29 (unhandled.log): 0x20EE command 1 with a usable object as target
RANK_SKILL_MAGIC = 0x52414E4B     # ping (0x2136) type the patched client sends for a skill's "+" (icserver/patcher.py)
RANK_BURST_GAP = 0.08             # s: rank pings closer than this are a HUD refresh, not a click
DRAFT_FLAG = 0x20000              # SetDraftMode's constant (0xa0c530 -> 0x2102)
BOUTIQUE_BASE = 0x0B00000000000000  # boutique ids of the server's store entries: base | DID
# 2026-10-28 15:00 (store-fix.md 3.2, C): 0x210E names the currency "SC" (Merits) / "HC" (Crisis Coins); the store
# page's forms and the fase3-ie names map to the same wallets
STORE_WALLETS = {"sc": "soft", "merits": "soft", "merit": "soft", "soft": "soft",
                 "hc": "hard", "crisiscoins": "hard", "crisis coins": "hard", "coins": "hard", "hard": "hard"}
STORE_PRICE_KEYS = {A.CT_AUGMENT: "augment", A.CT_MOD: "mod", A.CT_CHARACTER: "champion", A.CT_SKIN: "skin",
                    A.CT_AMP_SLOT: "amp_slot"}


class Match:
    def __init__(self, session, encounter, qflags):
        self.encounter, self.qflags = encounter, qflags
        self.champion = session.ic["champion"]     # the lobby's pick (0x20E4 / 0x2102), else [ics] champion
        self.group = Group(f"match s{session.sid}")
        self.lobby = None                          # ics.lobby.Lobby for champion select with bots
        self.custom = False
        self.lobby_at = None
        self.percent = 0
        self.created = False
        self.linked = False
        self.in_world = False
        self.pending_cinematic = 0                 # an intro cinematic asked for before load complete
        self.world = None
        self.director = None
        self.shop = None
        self.mode = None                           # the mode layer's handle (ics/match)
        self.mode_error = False
        self.rank_ping = (0.0, None)
        self.last_tick = None
        self.last_sent = 0.0
        self.started = None
        self.result = None
        self.sent_champions = []


class Session:
    _ids = iter(range(1, 1 << 30))

    def __init__(self, server, user_conn):
        self.server, self.cfg, self.data = server, server.cfg, server.data
        self.ic = self.cfg["ics"]
        self.sched = server.sched
        self.sid = next(Session._ids)
        self.user = user_conn
        self.user.session = self
        self.game = None
        self.phase = CONNECTED
        self.match = None
        self.custom = None                          # ics.lobby.CustomMatch while a custom match room is open
        self.account = None
        self.adata = A.AccountData.of(self.data)
        self.pending_reward = None
        self.pending_orders = {}
        self.group = Group(f"session {self.sid}")
        self.queue_group = Group(f"queue s{self.sid}")
        self.lock = threading.RLock()
        self.user_reader = FrameReader()
        self.game_reader = FrameReader()
        self.got_hello = False
        self.game_hello_done = False

    # ---- helpers ---------------------------------------------------------------------------
    def log(self, text):
        log.info(text, self)

    def set_phase(self, phase, why=""):
        if phase != self.phase:
            self.log(f"phase {self.phase} -> {phase}" + (f" ({why})" if why else ""))
            self.phase = phase

    def send(self, label, data):
        """Everything goes out on the login connection (also answers to game-connection events)."""
        return self.user.send(data, label)

    def send_many(self, labelled):
        return self.user.send_all(labelled)

    def later(self, delay, fn, group=None):
        def run():
            with self.lock:
                fn()
        self.sched.after(delay, run, group or self.group)

    def every(self, interval, fn, group, first_delay=None):
        def run():
            with self.lock:
                return fn()
        self.sched.every(interval, run, group, first_delay)

    def roster(self):
        roster = self.data.roster
        limit = int(self.ic.get("roster_limit", 0) or 0)
        return roster[:limit] if limit else roster

    def save_account(self):
        if self.account is not None and not self.account.save():
            self.log(f"WARNING: account file {self.account.path} could not be written")

    # ---- login connection ------------------------------------------------------------------
    def on_user_data(self, data):
        with self.lock:
            log.traffic("user <<", "recv", data, self)
            if not self.got_hello:
                self.got_hello = True
                self._hello(data)
                return
            for msg in self.user_reader.feed(data):
                self.handle(msg, "user")

    def _hello(self, data):
        blob = find_session_key_blob(data)
        scheme, plain = self.server.key.decrypt_session_key(blob) if blob else (None, None)
        self.log(f"login handshake OK ({scheme})" if plain else
                 "WARNING: session key not decrypted: the patched exe and the key do not match (python ic.py patch)")
        self.send("welcome (0x40000)", M.hello_reply(time.time()))
        self.account = A.Account.load(str(self.ic["player_name"]), self.ic)
        self.log(f"account '{self.account.name}' {'loaded' if self.account.loaded else 'created'} "
                 f"({self.account.path}): level {self.account.d['level']}, "
                 f"{self.account.wallet['soft']} Merits, {self.account.wallet['hard']} Crisis Coins")
        for gid in self.account.apply_grants():
            # [ics] account_grants (2026-10-29 22:30, the tester's store test): one-time Merits / Crisis Coins
            self.log(f"account grant {gid!r} applied: {self.account.wallet['soft']} Merits, "
                     f"{self.account.wallet['hard']} Crisis Coins")
            self.account.save()
        if not self.account.loaded:
            n = self.account.seed_achievements(self.adata)
            self.log(f"new account: {n} protector-level achievement(s) up to level {self.account.d['level']} marked done")
        self.send_many(self._login_events())
        self.set_phase(MENU, "account data sent")
        self.save_account()
        if self.ic.get("login_extras", True):
            self.later(float(self.ic.get("login_extras_delay", 0.5)), self._login_extras)

    def _advancement_rows(self):
        """0x209D rows: per champion (variant, level, XP, XP to next, last used, last ranked)."""
        acct, roster = self.account, self.roster()
        rows = []
        for c in roster:
            st = acct.d["champions"].get(f"0x{c['variant']:08X}", {})
            lvl = int(st.get("level", 1))
            # 2026-10-25 (stolen-powers-audit.md 4, P: every Stolen Power version carries the unlock rule 0x10000922,
            # its champion at level 5; with every champion reported at level 1 the picker offered only the 12 base
            # powers): champions are reported at least at [ics] champion_min_level
            lvl = max(lvl, int(self.ic.get("champion_min_level", 5) or 1))
            rows.append((c["variant"], lvl, int(st.get("xp", 0)), acct.xp_to_next(lvl, True),
                         int(st.get("last_used", 0)), int(st.get("last_ranked", 0))))
        return rows

    def _login_events(self):
        """The account data in the order the client needs (full-account-social.md 3): 0xEB, 0x20B8, 0x20ED, 0x209D,
        0x2024, 0x216A, 0x2120, 0x218B, 0x215D, 0xCE, 0x214B, 0x2080 last (it opens the landing screen)."""
        acct, roster = self.account, self.roster()
        events = M.initial_events(roster, int(acct.d["level"]), self.ic["player_name"],
                                  self.data.encounter_list() if self.ic.get("encounters_from_data", True) else None,
                                  self._queue_flags())
        if self.ic.get("queue_eligibility", True):
            # after 0x215D, before 0x2080 (the play menu asks GM_UI.InqQueueEligibility when it builds its list)
            k = next((i for i, (label, _d) in enumerate(events) if "(0x215d)" in label), len(events) - 1)
            events.insert(k + 1, self._eligibility_event())
        need = acct.xp_to_next(acct.d["level"])
        rows = self._advancement_rows()
        replace = {
            "(0x20b8)": ("ownables (0x20b8)", M.ownables(acct.ownable_items(roster, self.adata))),
            "(0x209d)": ("character advancement (0x209d)", M.character_advancement(rows)),
            # 2026-10-22 14:02 (tester: the second login hung at "Retrieving encounters" after the first session had
            # stored 5 preferences; the first login, with none, worked): the stored preferences are sent back only
            # with [ics] send_stored_preferences (the client keeps them in its own UserPreferences.ini anyway)
            "(0x216a)": (f"server options (0x216a): {len(self._server_options(acct))} preference(s)",
                         M.server_options(self._server_options(acct))),
            "(0x2080)": (f"account level (0x2080): {acct.d['level']}, {acct.d['xp']}/{need} XP",
                         M.account_level(acct.d["level"], acct.d["level"],
                                         *matchend.xp_numbers(self.ic, acct, acct.d["level"], acct.d["xp"]),
                                         0, 0, acct.d["xp"] / max(1, need), acct.d["xp"] / max(1, need),
                                         layout=str(self.ic.get("account_level_layout", "client")))),
        }
        out = []
        for label, data in events:
            key = next((k for k in replace if k in label), None)
            if key is not None:
                out.append(replace[key])
            elif "(0x2120)" in label:
                continue                       # sent by matchend.login_events (merged with the account's)
            else:
                out.append((label, data))
        out[-1:-1] = matchend.login_events(self.ic, acct, self.data)
        return out

    def _login_extras(self):
        """After the landing screen opened (full-protocol.md 4.1 "optional"): currencies, header + icons, best
        accolades, the login calendar's reward, the contact list."""
        acct = self.account
        if acct is None or self.user.closed:
            return
        out = [(f"currency balance (0x2081): {acct.wallet['hard']} / {acct.wallet['soft']}",
                M.currency_balance(acct.wallet["hard"], acct.wallet["soft"])),
               matchend.header_again(self.ic, acct),
               ("best accolades (0x2186): none yet", M.best_accolades()),
               ("contact list (0x203b): empty", M.contact_list())]
        if self.ic.get("login_calendar", True):
            out += self._login_reward()
        self.send_many(out)

    def _login_reward(self):
        """The calendar's due reward set (0x2197): granted at once (the client has no event to claim it,
        full-account-social.md 6.4); 0x219D when none is due."""
        acct = self.account
        due = acct.login_reward_due(self.adata)
        if not due:
            return [("login reward: none due (0x219d)", M.no_login_reward())]
        day, set_did = due
        entry = acct.add_pending_reward(self.adata, set_did, set_did, A.SOURCE_LOGIN)
        elements = acct.reward_elements([entry], day=day)
        _e, changed = acct.claim(self.adata, self.roster(), entry["instance"], set_did)
        acct.d["rewards"]["login_last_day"] = day
        self.save_account()
        out = [(f"login reward: day {day}, set {set_did:#x} (0x2197)", M.reward_sets(elements, 0x2197)),
               (f"currency balance (0x2081)", M.currency_balance(acct.wallet["hard"], acct.wallet["soft"]))]
        if changed:
            out.append((f"ownables changed (0x20b8): {len(changed)}",
                        M.ownables(acct.ownable_items(self.roster(), self.adata, changed))))
        return out

    def _server_options(self, acct):
        return acct.server_options() if self.ic.get("send_stored_preferences", False) else []

    # ---- the play menu's encounter list ------------------------------------------------------------------------------
    def _queue_flags(self):
        """[ics] queue_flags {category: flag word} (keys may be strings in config.toml)."""
        out = {}
        for k, v in (self.ic.get("queue_flags") or {}).items():
            try:
                out[int(str(k), 0)] = int(str(v), 0) if isinstance(v, str) else int(v)
            except ValueError:
                continue
        return out

    def _menu_encounters(self):
        """[(DID, category)] the menu lists (the same list as 0x2024)."""
        if self.ic.get("encounters_from_data", True):
            return list(self.data.encounter_list())
        return [(e, M.CATEGORY_TUTORIAL if "Tutorial" in name else 0) for e, name in M.ENCOUNTERS]

    def _eligibility_event(self):
        acct, roster = self.account, self.roster()
        level = int(acct.d["level"]) if acct else 1
        # the second value is compared with each encounter's player count + [0x1866B8C] (ranked); probably the
        # account's champion count [P]: the roster size (54) makes every encounter ranked-eligible
        encs = [did for did, _cat in self._menu_encounters()]
        return (f"queue eligibility (0x2101): level {level}, capacity {len(roster)}, {len(encs)} encounter(s)",
                M.queue_eligibility(level, len(roster), encs, int(self.ic.get("ranked_min_level", 1))))

    def _menu_refresh(self, why):
        """0x20FF (the encounter list again -> Encounter.ResetMapSelectionList -> the menu queries its encounters)
        and 0x2101, while the client is in the menu."""
        if self.user.closed or self.account is None or self.phase != MENU:
            return
        encs = self._menu_encounters()
        out = [(f"encounter list again (0x20ff): {len(encs)} encounter(s), {why}",
                M.encounter_update(encs, self._queue_flags()))]
        if self.ic.get("menu_refresh_account_data", True):
            # 2026-10-28 13:52 (tester: back in the lobby after a match, the champions, the last played champion and its
            # background did not load again): the account data the login sends goes again with the menu refresh:
            # owned champions / items (0x20B8), champion levels and last used (0x209D, the landing screen's champion and
            # background), completed encounters / last played (0x214B) and the currencies (0x2081)
            acct = self.account
            out += [("ownables again (0x20b8)", M.ownables(acct.ownable_items(self.roster(), self.adata))),
                    ("character advancement again (0x209d)", M.character_advancement(self._advancement_rows())),
                    (f"currency balance again (0x2081): {acct.wallet['hard']} / {acct.wallet['soft']}",
                     M.currency_balance(acct.wallet["hard"], acct.wallet["soft"]))]
            done = list(getattr(acct, "completed", []) or [])
            if done:
                out.append(("completed encounters again (0x214b)", M.completed_encounters(done, done[-1])))
        if self.ic.get("queue_eligibility", True):
            out.append(self._eligibility_event())
        self.send_many(out)

    def on_user_closed(self):
        with self.lock:
            self.log("login connection closed")
            self.end_match("login connection closed")
            self.queue_group.cancel()
            self.group.cancel()
            self.save_account()
            if self.game:
                self.game.close()

    # ---- game connection -------------------------------------------------------------------
    def attach_game(self, conn):
        with self.lock:
            if self.game and not self.game.closed:
                self.game.close()
            self.game = conn
            conn.session = self
            self.game_reader = FrameReader()
            self.game_hello_done = False

    def on_game_data(self, data):
        with self.lock:
            log.traffic("game <<", "recv", data, self)
            if not self.game_hello_done:
                self.game_hello_done = True
                self._game_hello()
                return
            for msg in self.game_reader.feed(data):
                self.handle(msg, "game")

    def _game_hello(self):
        m = self.match
        if m is None:
            self.log("game connection without a match")
            return
        g = self.game
        g.send(M.hello_reply(time.time()), "welcome (0x40000)")
        g.send(M.server_switch(1), "ServerSwitch (0x100)")
        out = [] if self._enter_match_at_launch(m) else self._last_played_msgs(m) + [self._enter_match_msg(m)]
        if not self._transition_at_launch(m):
            out.append(("end room check 0 (0x2016)", M.end_room_check(0)))
        self.send_many(out)
        if self.phase != LOBBY:
            # 2026-10-23 12:07: the client's ConnectToLobby (0x20F2) can come before this hello now that 0x20AF waits
            self.set_phase(GAME_CONNECTED)
        self.every(self.cfg["timing"]["keepalive"], lambda g=g: self._keepalive(g), self.group)

    def _last_played_msgs(self, m):
        """0x214B with the match's encounter as "last played": the client's map manager loads its minimap / map info
        from it (2026-10-23 15:23, diag: LoadMap(0x40000991) in a Crime Alley match: the login's 0x214B said Tutorial 1
        was last played). [ics] last_played_at_match."""
        if not self.ic.get("last_played_at_match", True):
            return []
        done = list(self.account.completed) if self.account is not None else []
        return [(f"completed encounters (0x214b), last played {m.encounter:#x}", M.completed_encounters(done, m.encounter))]

    def _enter_match_msg(self, m):
        enc = self.cfg.encounter(m.encounter) or {}
        packs, champions = self._match_content(m, enc)
        m.sent_champions = list(champions)
        return (f"enter match (0x20af): packs {' '.join(hex(p) for p in packs)}",
                M.enter_match(m.encounter, champions[0], packs, champions[1:]))

    def _match_content(self, m, enc):
        """Packs and champions the client must load for this match (0x20AF), from the encounter's data: its map
        pack's list (zone, layout, variants ...), then each champion's model pack (the lobby's bots too). The client
        loads exactly what it is told (gmConnectionManager::LoadParentRPs, 0xA99370); 2026-10-21 (tester: the map
        loads only in part, no vehicles) the layout 0xA0000256 and variants 0xA0000257 packs were never sent."""
        info = self.data.encounter(m.encounter)
        others = list(m.lobby.champions()) if m.lobby else []
        champions = [m.champion]
        for c in others + list(info["champions"]) + list(enc.get("extra_champions", ())):
            if c not in champions:
                champions.append(c)
        packs = list(info["packs"]) + [p for p in enc.get("packs", ()) if p]
        if m.lobby:
            packs += [p for p in (self._mode_call("extra_packs", m.encounter) or ()) if p and p not in packs]
            # 2026-10-25 (black-ground-shapes.md 4.2): extra packs per map, e.g. 0xA00002E6 (the socket cover 0x2E00119F)
            # for Gotham Divided ([ics] match_extra_packs: map key -> [pack]; untested, empty by default)
            mod = self._mode_module()
            mp = mod.maps.map_for(m.encounter)[0] if mod is not None and hasattr(mod, "maps") else None
            for p in ((self.ic.get("match_extra_packs") or {}).get((mp or {}).get("key", "")) or ()):
                p = int(str(p), 0)
                if p and p not in packs:
                    packs.append(p)
        for c in champions:
            if self.ic.get("champion_shared_packs", True):
                packs += [p for p in self.data.champion_shared_packs(c) if p not in packs]
        # 2026-10-23 16:20 (tester: a costume shows another model's parts; Bat Flight wrong with some skins): the
        # model packs of one champion's variants carry the same DIDs with different content (0x36000009: 68 KB in
        # Samurai 0xA000010C, 46 KB in the base 0xA0000076, its own in Android 0xA00002F3) and the last pack loaded
        # wins, so the local champion's model pack goes last ([ics] local_champion_pack_last)
        order = list(champions[1:]) + champions[:1] if self.ic.get("local_champion_pack_last", True) else champions
        for c in order:
            heavy = self.data.champion_pack(c)
            if heavy and heavy not in packs:
                packs.append(heavy)
        resident = set(self.ic.get("resident_packs") or ())
        if resident & set(packs):
            # already loaded at start-up; naming them would unload them at the match's end (menu without encounters)
            self.log("0x20AF leaves out start-up packs " + " ".join(hex(p) for p in packs if p in resident))
            packs = [p for p in packs if p not in resident]
        if self.ic.get("enter_match_check_packs", True):
            # 2026-10-25 (match-load-sequence.md, C: exactly one unknown pack id fails the client's whole load request
            # and the load stops): ids that are 0 or not in the player's pack folder are dropped and logged
            rp = getattr(self.data.packs, "rp_dir", None)
            if rp and os.path.isdir(rp):
                have = {f.lower() for f in os.listdir(rp)}
                bad = [p for p in packs if not p or f"0x{p:08x}.rp" not in have]
                if bad:
                    self.log("0x20AF drops unknown packs " + " ".join(hex(p) for p in bad))
                    packs = [p for p in packs if p not in bad]
        self.log(f"encounter {m.encounter:#x}: map pack {info['map_pack']:#x}, "
                 f"{len(info['packs'])} packs from it, champions {' '.join(hex(c) for c in champions)}")
        return packs, champions

    def _keepalive(self, g):
        if g.closed or g is not self.game:
            return False
        g.send(M.time_packet(time.time()), "time")
        return True

    def on_game_closed(self, conn):
        with self.lock:
            if conn is self.game:
                self.log("game connection closed")
                self.end_match("game connection closed")

    def end_match(self, why):
        if self.match:
            self.match.group.cancel()
            self.match = None
            self.log(f"match ended: {why}")
        if self.phase in MATCH_PHASES or self.phase == QUEUED:
            self.set_phase(MENU, why)

    # ---- client events -----------------------------------------------------------------------
    def handle(self, msg, via):
        log.traffic(f"{via} <<", f"event {msg.event_id:#x}", msg.body, self)
        handler = HANDLERS.get(msg.event_id)
        try:
            result = handler(self, msg) if handler is not None else NotImplemented
        except Exception:                                    # noqa: BLE001
            if not self.ic.get("handler_errors_keep_connection", True):
                raise
            # 2026-10-24 00:55 (tester: the match closed when an emote arrived; a bug in the 0x9F handler): a handler's
            # error is logged and the connection stays up
            self.log(f"INTERNAL ERROR in the {msg.event_id:#x} handler (connection kept)\n" + traceback.format_exc())
            return
        if result is NotImplemented:
            log.unhandled(msg, self)

    # ---- queue ---------------------------------------------------------------------------------
    def ev_join_queue(self, msg):
        """0x20EB JoinQueue {QueueKey(encounter, flags), u8, u32}."""
        if len(msg.body) < 8:
            return NotImplemented
        if self.phase in MATCH_PHASES:
            self.log("JoinQueue ignored: a match is being set up")
            return
        did, qflags = struct.unpack_from("<II", msg.body, 0)
        if self.ic.get("reject_unknown_encounters", True) and not self._joinable(did):
            # the client builds the QueueKey from the encounter's template (0x86E060): (0, 0) when that template did
            # not load on its side, so the map tile it came from showed no data either
            self.log(f"JoinQueue for encounter {did:#x} flags {qflags:#x} refused: "
                     + ("the client could not load the encounter (QueueKey 0)" if not did else "no map pack")
                     + "; removed from queue + the encounter list again")
            self.send("removed from queue (0x20e0)", M.removed_from_queue())
            self._menu_refresh("after a refused JoinQueue")
            return
        self.start_queue(did, qflags)

    def _joinable(self, did):
        if not did or did == 0xFFFFFFFF:
            return False
        if self.cfg.encounter(did) or did in dict(self._menu_encounters()):
            return True
        return bool(self.data.encounter(did).get("map_pack"))

    def start_queue(self, did, qflags, custom=False):
        if self.game is not None:
            self.game = None              # the previous match's connection: the client replaces it
        self.queue_group.cancel()
        self.queue_group = Group(f"queue s{self.sid}")
        enc = self.cfg.encounter(did)
        self.match = m = Match(self, did, qflags)
        m.custom = custom
        required = self.data.encounter(did).get("champions") or []
        if required:
            # the encounter names its champion (template 0x10000AE6: Tutorial 1 -> Gaslight Batman)
            m.champion = required[0]
        threading.Thread(target=lambda: self.data.prepare(self.data.encounter(did), self.server.flow_classes(did)),
                         daemon=True).start()
        lobby = not required and is_lobby_encounter(self.adata, self.cfg, did)
        if lobby:
            m.champion = self._default_pick()
            m.lobby = Lobby(self, did, qflags, m.champion)
            self.log(f"joined queue for encounter {did:#x}: champion select with "
                     f"{sum(1 for s in m.lobby.slots if s.bot)} bot(s), {m.lobby.per_team} per team")
        else:
            self.log(f"joined queue for encounter {did:#x}" + ("" if enc else " (no [ics.encounters] entry: "
                                                                            "packs and spawn unknown)"))
        if custom:
            self.set_phase(QUEUED)
            return
        self.send(f"joined queue (0x20c0) {did:#x}", M.joined_queue(did, qflags))
        self.set_phase(QUEUED)
        pop = float(self.ic.get("queue_pop_seconds", 2.0) or 0.0) if lobby else 0.0
        found = lambda: self.send("match found (0x20fa)", M.match_found(1, int(self.ic.get("accept_seconds", 30))))
        if pop > 0:
            self.later(pop, lambda: found() if self.match is m and self.phase == QUEUED else None, self.queue_group)
        else:
            found()

    def _default_pick(self):
        """The lobby's first pick: the most recently played champion the account owns, else [ics] champion."""
        acct = self.account
        best = None
        if acct is not None:
            used = sorted(((v.get("last_used", 0), k) for k, v in acct.d["champions"].items()), reverse=True)
            for _t, k in used:
                did = int(k, 16)
                if self.data.kit(did) and acct.champion_owned(did):
                    best = did
                    break
        return best or int(self.ic["champion"])

    def ev_leave_queue(self, msg):
        """0x20C3 LeaveQueue -> 0x20E0 removed from queue."""
        if self.phase != QUEUED:
            self.log(f"LeaveQueue in phase {self.phase}: nothing to leave")
        self.queue_group.cancel()
        if self.match and self.phase == QUEUED:
            self.match.group.cancel()
            self.match = None
        self.send("removed from queue (0x20e0)", M.removed_from_queue())
        if self.phase == QUEUED:
            self.set_phase(MENU, "left the queue")

    def ev_accept_match(self, msg):
        if self.phase != QUEUED or not self.match:
            return
        self._referral()

    def _referral(self):
        m, s = self.match, self.cfg["server"]
        self.server.expect_game(self)
        self.send_many([("players accepted (0x20ad)", M.players_accepted(1)),
                        ("lobby room created (0x2028)", M.lobby_room_created(m.encounter, m.qflags)),
                        (f"referral -> {s['host']}:{s['game_port']}", M.referral(s["host"], s["game_port"]))])
        self.set_phase(REFERRED)

    # ---- lobby ---------------------------------------------------------------------------------
    def ev_connect_to_lobby(self, msg):
        m = self.match
        if not m:
            return
        ic, room = self.ic, self.ic["room_id"]
        if m.lobby:
            out = m.lobby.state_msgs()
        else:
            out = [("lobby player slot (0x2029)", M.lobby_player(m.champion, ic["player_name"], ic["team"], room)),
                   ("lobby state (0x204c)", M.lobby_state(m.encounter, m.qflags, m.champion, room))]
        if not self._transition_at_launch(m):
            out += self._transition_msgs(room)
        if m.lobby_at is None and getattr(self, "matches_entered", 0) and ic.get("resend_local_player", True):
            # 2026-10-23 22:34 (tester: the second match of a session stays at 35 %; second-match-load-hang.md): the
            # client's world teardown (0xa99b60 -> 0x7d14b0 -> 0x635250(0, 0)) clears the local player IID and only
            # 0xEB sets it again; without it the player object is never "local" (0x64dac0 / 0x69bd90) and the 55 %
            # step 0xa0a570 never runs. The old server re-sent it the same way (icserver resend_local_player)
            out = [("set local player again (0xeb)", M.set_local_player())] + out
        if m.lobby_at is None:
            self.matches_entered = getattr(self, "matches_entered", 0) + 1
        self.send_many(out)
        if m.lobby_at is not None:
            return
        m.lobby_at = time.monotonic()
        self.set_phase(LOBBY)
        if m.lobby:
            m.lobby.opened_at = time.monotonic()
            self.log(f"champion select: {m.lobby.select_seconds:.0f} s")
            self.every(0.25, self._lobby_tick, m.group, first_delay=0.25)
        self.every(0.25, self._maybe_create, m.group, first_delay=0.25)

    def ev_loading_percent(self, msg):
        m = self.match
        if len(msg.body) < 4 or not m:
            return NotImplemented
        m.percent = max(m.percent, struct.unpack_from("<I", msg.body, 0)[0])
        self.log(f"client loading {m.percent}%")
        bots = int(self.ic.get("bot_loading_percent", 100))
        if m.lobby and bots >= 0:
            entries = [(s.team, s.index, m.percent if s is m.lobby.me else bots) for s in m.lobby.slots]
            self.send(f"loading percent {m.percent}, bots {bots} (0x2031)", M.loading_percents(entries, m.lobby.room))
            return
        self.send(f"loading percent {m.percent} (0x2031)", M.loading_percent(self.ic["team"], m.percent, self.ic["room_id"]))

    def _enter_match_at_launch(self, m):
        """Champion select: 0x20AF sets lobby+0x4CB (no lobby pack loading), so it waits for the countdown's end."""
        return bool(m.lobby) and self.ic.get("lobby_enter_match_at_launch", True)

    def _transition_at_launch(self, m):
        """Champion select: 0x2016 / 0x206D move the client to the loading screen, so they wait for the launch."""
        return bool(m.lobby) and self.ic.get("lobby_transition_at_launch", True)

    @staticmethod
    def _transition_msgs(room):
        """0x2016 SetLobbyTransition (UI event 0x23, to the loading screen), 0x206D everyone loaded (event 0x33)."""
        return [("end room check (0x2016)", M.end_room_check(room)), ("all loaded? (0x206d)", M.all_loaded(room))]

    def _lobby_tick(self):
        m = self.match
        if not m or not m.lobby or m.lobby.launching:
            return False
        lob = m.lobby
        if lob.all_locked() or time.monotonic() - lob.opened_at >= lob.select_seconds:
            self._launch(m, "every pick locked" if lob.all_locked() else "champion select time over")
            return False
        return True

    def _launch(self, m, why):
        """Champion select over: the picks lock, launch warning 0x204B (the costume countdown, launch_delay s), then
        0x2016 + 0x206D to the loading screen (0x2053 only with send_match_started: it means view-match); the
        objects follow once the client loads (_maybe_create)."""
        lob = m.lobby
        if lob.launching:
            return
        lob.launching = True
        if not lob.me.locked:
            lob.me.locked = True
        m.champion = lob.me.champion
        if self.account is not None:
            self.account.champion(self.data.base_variant(m.champion) or m.champion)["last_used"] = int(time.time())
        delay = float(self.ic.get("launch_delay", 3.0))
        start, end = launch_times(delay)
        self.log(f"champion select over ({why}): {self.data.champion_name(m.champion)[0]} ({m.champion:#x}) vs "
                 + ", ".join(f"{s.name} t{s.team}" for s in lob.slots if s.bot))
        out = [lob.slot_msg(lob.me), (f"launch warning (0x204b): {delay:.0f} s to choose a costume",
                                      M.launch_warning(start, end, lob.room))]
        self.send_many(out)

        def started():
            if self.match is not m:
                return
            lob.launched = True
            m.lobby_at = time.monotonic()          # the object timing (_maybe_create) counts from the launch
            msgs = []
            if self.ic.get("send_match_started", False):
                msgs.append(("match started (0x2053)", M.match_started(lob.room)))   # view-match mode, see config
            if self._enter_match_at_launch(m) or (self.ic.get("resend_enter_match_on_pick", True)
                                                   and m.sent_champions[:1] != [m.champion]):
                msgs += self._last_played_msgs(m) + [self._enter_match_msg(m)]
            if self._transition_at_launch(m):
                msgs += self._transition_msgs(lob.room)
            self.send_many(msgs)
        self.later(delay, started, m.group)

    def _lobby_or_none(self):
        m = self.match
        return m.lobby if m and m.lobby and self.phase in (GAME_CONNECTED, LOBBY) else None

    def _pick(self, msg, event):
        """A champion pick: 0x20E4 SelectCharacter (full-account-social.md) or 0x2102 (full-protocol.md); both u32
        variant | u8 [| u32]."""
        m = self.match
        if len(msg.body) < 4:
            return NotImplemented
        did = struct.unpack_from("<I", msg.body, 0)[0]
        self.log(f"champion pick {did:#x} sent as {event:#x}"
                 + (" (SelectCharacter per full-account-social.md)" if event == 0x20E4
                    else " (SelectCharacter per full-protocol.md; full-account-social.md: custom-match draft toggle)"))
        if not m:
            return
        if m.created or self.data.encounter(m.encounter).get("champions"):
            self.log(f"champion pick {did:#x} ignored (the match has its champion {m.champion:#x})")
            return
        if not self.data.kit(did):
            self.log(f"champion pick {did:#x}: no such champion variant in the roster")
            return
        ic, room = self.ic, self.ic["room_id"]
        if m.lobby:
            out = m.lobby.pick(did)
            if out is None:
                self.log(f"champion pick {did:#x} refused (locked, taken by a teammate or not owned)")
                self.send("lock failed (0x2005)", M.lock_failed(room, did))
                return
            m.champion = did
            self.log(f"champion picked: {self.data.champion_name(did)[0]} ({did:#x})")
            self.send_many(out)
            again = float(self.ic.get("lobby_slot_resend", 0.5) or 0)
            if again > 0 and not m.lobby.launched:
                # 2026-10-23 14:00 (tester: a costume's portrait empties): the client asks for a pick's packs only
                # when no load runs (0xabc620 "Already Loading"); the slot again a moment later starts it
                lob = m.lobby
                self.later(again, lambda: self.send_many([lob.slot_msg(lob.me)])
                           if self.match is m and not lob.launched and lob.me.champion == did else None, m.group)
            return
        m.champion = did
        self.log(f"champion picked: {self.data.champion_name(did)[0]} ({did:#x})")
        self.send_many([("lobby player slot (0x2029)", M.lobby_player(did, ic["player_name"], ic["team"], room)),
                        ("lobby state (0x204c)", M.lobby_state(m.encounter, m.qflags, did, room))])

    def ev_select_character(self, msg):
        return self._pick(msg, 0x20E4)

    def ev_select_or_draft(self, msg):
        """0x2102: u32 | u8. With the constant 0x20000 it is SetDraftMode (custom match, 0xa0c530); else a pick."""
        if len(msg.body) >= 5 and struct.unpack_from("<I", msg.body, 0)[0] == DRAFT_FLAG:
            enabled = bool(msg.body[4])
            self.log(f"0x2102 = custom-match SetDraftMode ({'on' if enabled else 'off'})")
            if self.custom:
                self.custom.draft = enabled
            self.send(f"custom match draft mode (0x2103) {enabled}", M.cm_draft_mode(DRAFT_FLAG, enabled))
            return
        return self._pick(msg, 0x2102)

    def ev_lock(self, msg):
        """0x208E PlayerChangedCharacterLockStatus: u32 variant | u8 lock | u32."""
        lob = self._lobby_or_none()
        if lob is None or len(msg.body) < 5:
            return NotImplemented if lob is None else None
        did, lock = struct.unpack_from("<IB", msg.body, 0)
        self.log(f"lock status {did:#x} {'locked' if lock else 'unlocked'} (0x208e)")
        if lock:
            out = lob.lock(did)
            if out is None:
                self.send("lock failed (0x2005)", M.lock_failed(lob.room, did))
                return
            self.match.champion = lob.me.champion
            self.send_many(out)
        elif not lob.launching:
            lob.me.locked = False
            self.send_many([lob.slot_msg(lob.me)])

    def ev_early_launch(self, msg):
        """0x2089 PlayerSelectedEarlyLaunch (full-account-social.md); 0x206A in full-protocol.md (see ev_0x206a)."""
        lob = self._lobby_or_none()
        if lob is None:
            return NotImplemented
        self.log("early launch selected")
        self.send("early launch (0x206c)", M.early_launch_selected(str(self.ic["player_name"]), lob.room))
        self._launch(self.match, "early launch")

    def ev_change_stolen_power(self, msg):
        """0x207D RequestChangeStolenPower: u32 slot | u32 power -> 0x2004."""
        lob = self._lobby_or_none()
        if len(msg.body) < 8:
            return NotImplemented
        slot, power = struct.unpack_from("<II", msg.body, 0)
        self.log(f"Stolen Power slot {slot} -> {power:#x} (0x207d)")
        if lob is not None:
            self.send_many(lob.change_stolen_power(slot, power))
        elif self.account is not None:
            self.account.set_stolen_power(self.data, self.match.champion if self.match else self.ic["champion"],
                                          slot, power)
        self.save_account()

    def ev_change_amplifier_set(self, msg):
        """0x2098 RequestChangeAmplifierSet (u32 slot | u32 default-set DID, full-account-social.md) or 0x200D (u8
        slot, account-systems-data.md 1.4) -> 0x204A."""
        lob = self._lobby_or_none()
        if lob is None:
            return NotImplemented
        slot = msg.body[0] if msg.event_id == 0x200D else struct.unpack_from("<I", msg.body, 0)[0]
        self.log(f"amplifier set {slot} chosen ({msg.event_id:#x})")
        self.send_many(lob.change_amplifier_set(slot))
        if self.account is not None:
            # 2026-10-28 (store-amplifiers.md): remembered per champion for the next lobby and for the match's stats
            self.account.select_amplifier_set(lob.me.champion, slot)
            self.save_account()

    def ev_trade(self, msg):
        """0x20D6 Draft_RequestTrade (u64 player) / 0x2026 (u64, u32) in the lobby: bots accept at once."""
        lob = self._lobby_or_none()
        if lob is None or len(msg.body) < 8:
            return NotImplemented
        target = struct.unpack_from("<Q", msg.body, 0)[0]
        out = lob.trade(target)
        self.log(f"draft trade with {target:#x}: {'done' if out else 'refused'} ({msg.event_id:#x})")
        if out:
            self.match.champion = lob.me.champion
            self.send_many(out)

    def ev_exit_lobby(self, msg):
        """0x20BF ExitLobbyToMainMenu (or 0x200A outside a custom match) -> 0x2021 and back to the menu."""
        m = self.match
        if not m or self.phase not in MATCH_PHASES:
            return NotImplemented
        self.log(f"client leaves the lobby ({msg.event_id:#x})")
        self.send("exit lobby (0x2021)", M.exit_lobby(self.ic["room_id"]))
        self.end_match("left the lobby")

    def _maybe_create(self):
        m, t = self.match, self.cfg["timing"]
        if not m or m.created or m.lobby_at is None:
            return False
        if m.lobby and not m.lobby.launched:
            return True
        waited = time.monotonic() - m.lobby_at
        if m.lobby and self.ic.get("objects_on_level_loaded", True):
            # 2026-10-25 (match-load-sequence.md, C: the client reaches 35 % without any object, at 17:52 the objects
            # went out at 10 % after the 10 s fallback while Gotham Heights' packs still loaded): objects once the
            # level is loaded (0xCC) or the client is at 35 %, the fallback after [ics] objects_level_max_wait
            ready = getattr(m, "level_loaded", False) or m.percent >= 35
            if not (ready and waited >= t["objects_min_delay"]) and waited < float(self.ic.get("objects_level_max_wait", 30.0)):
                return True
        elif not (waited >= t["objects_min_delay"] and m.percent >= t["objects_min_percent"]) and waited < t["objects_max_wait"]:
            return True
        m.created = True
        enc = self.cfg.encounter(m.encounter) or {}
        mode_mod = self._mode_module() if m.lobby else None
        spawn = enc.get("spawn")
        if not spawn and m.lobby:
            spawn = self._mode_call("spawn_point", m.encounter, int(self.ic["team"]))
        spawn = spawn or [1, 0x13, 0xCB, 0, 0.0, 0.0, 0.0]
        w = World(self.data, self.cfg, m.encounter, spawn,
                  send=lambda label, data: self.send(label, data),
                  schedule=lambda delay, fn: self.later(delay, fn, m.group),
                  log=self.log)
        w.ground_z = float(enc.get("ground_z", 0.0) or 0.0)
        nav = self.data.navgrid(m.encounter, spawn[1:3])
        w.nav = nav.copy() if nav else None
        w.champion_sender = lambda label, m=m: self.send(label, self._objects(m.linked))
        if m.lobby is not None and self.ic.get("lobby_stolen_powers", True):
            w.stolen_choice = list(m.lobby.me.stolen)
        w.create_champion(m.champion, spawn)
        if m.lobby is not None and self.account is not None and self.ic.get("amplifier_stats_in_match", True):
            # 2026-10-28 ~13:52 (store-amplifiers.md): the lobby's set gives its augments' stats, apart from the items'
            add, pct = self.account.amplifier_bonuses(self.adata, m.lobby.me.amp)
            if add or pct:
                w.champion.amp_add, w.champion.amp_pct = add, pct
                w.recompute_stats(w.champion, refill=True)
                self.log(f"amplifier set {(m.lobby.me.amp or {}).get('slot', 0)}: " + ", ".join(
                    [f"{k:#x}+{v:g}" for k, v in sorted(add.items())] + [f"{k:#x}+{v:g}%" for k, v in sorted(pct.items())]))
        if m.lobby is not None and self.ic.get("match_start_ranks") is not None:
            # 2026-10-23 15:10 (tester: every skill is active from the start): a lobby match starts with the skills at
            # rank 0 (the basic attack and the Stolen Powers ready) and a skill point to spend
            start = {int(k): int(v) for k, v in (self.ic.get("match_start_ranks") or {}).items()}
            w.champion.ranks = {slot: start.get(slot, 0) for slot in w.champion.kit}
            w.champion.skill_points = int(self.ic.get("match_start_skill_points", 1))
        m.world = w
        m.shop = Shop(w, m.encounter)
        w.champion.gold = float(self.ic.get("start_credits", 0) or 0)
        flow = self._flow(m)
        if flow is not None:
            start = getattr(flow, "START", {})
            ch = w.champion
            ch.ranks = {slot: int((start.get("ranks") or {}).get(slot, 0)) for slot in ch.kit}
            ch.level = int(start.get("level", 1))
            ch.skill_points = int(start.get("skill_points", 0))
            m.director = D.Director(self, w, flow, m.encounter)
        if mode_mod is not None:
            try:
                m.mode = mode_mod.start_match(w, self, m.encounter, m.lobby.players())
                self.log(f"mode layer started for {m.encounter:#x} ({len(m.lobby.players())} players)")
            except Exception as e:
                self.log(f"mode layer start_match failed: {e!r}")
                m.mode = None
        self.log(f"objects: champion + player ({waited:.1f} s after the lobby, client at {m.percent}%)")
        self.send("create champion + player", self._objects(link=False))
        self.set_phase(LOADING)
        self.later(t["link_delay"], self._link, m.group)
        self.every(1.0 / t["tick_hz"], self._tick, m.group)
        return False

    def _mode_module(self):
        """ics/match (the mode layer: start_match(world, session, encounter, players) and tick(dt)), or None while
        it does not exist, or [ics] pvp_mode_layer is off."""
        if not self.ic.get("pvp_mode_layer", True):
            return None
        try:
            mod = importlib.import_module("ics.match")
        except Exception:                          # absent, or another engineer's work in progress
            return None
        return mod if hasattr(mod, "start_match") else None

    def _mode_call(self, name, *args):
        """An optional helper of the mode layer (spawn_point(encounter, team), extra_packs(encounter)), on the
        package or its maps module; None when it does not exist or fails."""
        fn = None
        for modname in ("ics.match", "ics.match.maps"):
            try:
                fn = getattr(importlib.import_module(modname), name, None)
            except Exception:
                fn = None
            if fn is not None:
                break
        if fn is None:
            return None
        try:
            return fn(*args)
        except Exception as e:                     # never break the load for the mode layer
            self.log(f"mode layer {name} failed: {e!r}")
            return None

    def _flow(self, m):
        """The encounter's flow module (ics/encounters/<director>.py), or None."""
        name = str((self.cfg.encounter(m.encounter) or {}).get("director", "") or "")
        if not name:
            return None
        try:
            return importlib.import_module(f"ics.encounters.{name}")
        except ImportError as e:
            self.log(f"encounter flow '{name}' not found ({e})")
            return None

    def encounter_info(self):
        m = self.match
        enc = dict(self.data.encounter(m.encounter))
        enc.update({k: v for k, v in (self.cfg.encounter(m.encounter) or {}).items() if k in ("layout_pack", "variants_pack")})
        return enc

    def show_hud(self, elements=None):
        """0x213D ShowElement for these HUD elements (None = every element of catalog hud_elements.tsv)."""
        elements = self.data.hud_elements() if elements is None else elements
        self.send_many([(f"HUD element {e} shown (0x213d)", M.hud_element(e, M.HUD_SHOW)) for e in elements])

    def hud_event(self, element, event, highlight=0, label=None):
        self.send(label or f"HUD element {element}: event {event}, highlight {highlight} (0x213d)",
                  M.hud_element(element, event, highlight))

    def play_cinematic(self, cin):
        m = self.match
        if m and not m.in_world and self.ic.get("cinematic_after_load", True):
            m.pending_cinematic = cin          # played once the client is in the world (ev_notice, load complete)
            self.log(f"cinematic {cin:#x} waits for the load to complete")
            return
        self._play_cinematic(cin)

    # ---- the end of a match --------------------------------------------------------------------------------------
    def victory(self, seconds):
        """2026-10-22 (decompiled, docs/re-notes/client-cinematics-matchend.md): VICTORY in the world first (the
        match-ended notice makes the client leave at once), then the notice with the end page's data: completed
        encounters, stats (the post-match movie), trainee achievement, scorecard; the reward is pulled later."""
        m, team = self.match, self.ic["team"]
        if m and m.lobby:
            return self.match_result(team, seconds)
        self.log(f"victory after {seconds:.0f} s")
        if not self.ic.get("tutorial_end_sequence", True):
            self.send(f"match ended, team {team} wins (0x1000000e)", M.match_ended(team, seconds))
            return
        self.send_many(matchend.victory_banner(self.ic, team))

        def end():
            msgs, self.pending_reward = matchend.match_end(self.ic, m.encounter, team, seconds,
                                                           level=getattr(m.world.champion, "level", 7) or 7,
                                                           account=self.account, data=self.data)
            self.send_many(msgs)
            for delay in self.ic.get("scorecard_resend", [5.0, 25.0, 60.0]) or []:
                self.later(float(delay), lambda: self.send_many(matchend.scorecard_bundle(
                    self.ic, m.encounter, account=self.account)) if self.match is None or self.match is m else None)
        self.later(float(self.ic.get("victory_hold", 4.0)), end)

    def match_result(self, winning_team, seconds=None, stats=None, announced=False):
        """The end of a lobby match (the stub's, a surrender, or the mode layer's): rewards to the account, VICTORY /
        DEFEAT, then (victory_hold s) the match-ended notice and the end page; the client leaves the world (0x12D)
        and gets 0x2021. stats (optional): {"kills": n, "players": [(player iid, champion iid)], "custom": bool}.
        announced = the mode layer has already shown the billboard and sent the match-ended notice."""
        m = self.match
        if not m or m.result is not None:
            return
        if seconds is None:
            seconds = time.monotonic() - (m.started or time.monotonic())
        m.result = winning_team
        stats = dict(stats or {})
        stats.setdefault("custom", m.custom)
        players = m.lobby.players() if m.lobby else [{"iid": M.LOCAL_PLAYER_ID}]
        banner, end, pending = matchend.pvp_match_end(self, m.encounter, int(self.ic["team"]), int(winning_team),
                                                      float(seconds), m.champion, players, stats,
                                                      notice=not announced)
        if pending:
            self.pending_reward = pending
        # 2026-10-30 tester report 11:23 (scorecard-panel-turret-head.md 1, C 0xA61DA0 / 0xA7E0A0): an empty 0x2188 never
        # reaches Flash, so the late copy is the 0x2104 that carries the encounter ([ics] scorecard_accolades_resend_event)
        which = "0x2188" if str(self.ic.get("scorecard_accolades_resend_event", "0x2104")).lower() == "0x2188" else "0x2104"
        late = [e for e in end if e[0].startswith("accolades (0x2188)" if which == "0x2188" else "champion level/XP (0x2104)")]
        self.late_accolades = (f"accolades again after the scorecard loaded ({which})", late[0][1]) if late and float(
            self.ic.get("scorecard_accolades_resend", 1.5) or 0) > 0 else None
        if announced:
            self.send_many(end)
            self._accolades_fallback()
            return
        self.send_many(banner)

        def finish():
            self.send_many(end)
            self._accolades_fallback()
        self.later(float(self.ic.get("victory_hold", 4.0)), finish)

    def _accolades_fallback(self):
        delay = float(self.ic.get("scorecard_accolades_resend_fallback", 8.0) or 0)
        if delay > 0 and getattr(self, "late_accolades", None):
            self.later(delay, self._send_late_accolades)
        delay = float(self.ic.get("scorecard_chat_summary_fallback", 9.0) or 0)
        if delay > 0 and getattr(self, "scorecard_chat", None):
            self.later(delay, self._send_scorecard_chat)

    def _send_scorecard_chat(self):
        """2026-10-30 tester report 14:51 (scorecard-rewards-side-panel.md): the result, duration and rewards as chat
        lines in the Scorecard view's chat window, once the scorecard is up ([ics] scorecard_chat_summary)."""
        lines, self.scorecard_chat = getattr(self, "scorecard_chat", None), None
        if lines:
            self.send_many(lines)

    def _send_late_accolades(self):
        """2026-10-29 tester report 23:03 (scorecard-accolades-meteor-aura.md 1): 0x2188 once more after the scorecard
        has its other data, so ScorecardManager raises ACCOLADES_RECVD and the Accolades tab's chain runs
        ([ics] scorecard_accolades_resend)."""
        late, self.late_accolades = getattr(self, "late_accolades", None), None
        if late:
            self.send_many([late])

    def match_over(self, winner, seconds, stats=None):
        """The mode layer's call (ics/match: after its billboard and its 0x1000000E notice)."""
        self.match_result(winner, seconds, stats, announced=True)

    def ev_end_page_closed(self, msg):
        """0x20A6: the end page (MISSION COMPLETE) closed: a 0x2190 makes the client hand its pending reward on.
        full-protocol.md 4.8 also names 0x20A6 the chat channel list (u32 n x StringInfo): then the channels'
        member lists (0x2135) go too."""
        channels = chat.parse_channels(msg.body)
        if channels:
            self.log(f"chat channels joined (0x20a6): {', '.join(channels)}")
            self.send_many([(f"chat members of {c} (0x2135)", M.chat_members(c, [M.LOCAL_PLAYER_ID]))
                            for c in channels])
        else:
            self.log("client closed the end page (0x20a6)")
        self.later(0.5, lambda: self.send_many([matchend.header_again(self.ic, self.account)]))
        delay = float(self.ic.get("menu_refresh_on_end_page_closed", 1.0) or 0.0)
        if delay > 0:
            # 2026-10-28 13:52 (tester: after the score screen the HOME menu was empty; timeline-kda-endscreen.md 3, P):
            # the menu's encounter list and eligibility again once the landing screen is up (the +3 s refresh after
            # 0x12D went while the end page was still open)
            self.later(delay, lambda: self._menu_refresh("end page closed"))

    def ev_ask_achievement_banners(self, msg):
        """0x212E: the end page asks for its achievement notifications -> 0x211F and the pending reward."""
        self.log("client asks for achievement banners (0x212e)")
        out = [matchend.achievement_banners(self.account, self.data)]
        if self.pending_reward:
            out.append(self.pending_reward)
        self.send_many(out)
        if getattr(self, "late_accolades", None):
            # the scorecard screen's AskForRibbons: its Init follows within ~0.2 s (traffic 22:51:50.629 -> .799)
            self.later(float(self.ic.get("scorecard_accolades_resend", 1.5) or 0), self._send_late_accolades)
        if getattr(self, "scorecard_chat", None):
            self.later(float(self.ic.get("scorecard_chat_summary_delay", 2.5) or 0), self._send_scorecard_chat)

    def ev_ask_pending_rewards(self, msg):
        """0x2124: the UI asks for the pending reward sets -> 0x2125 (the tutorial's Champion Unlocked, or the
        account's pending achievement rewards)."""
        pending = self.pending_reward
        if pending is None and self.account is not None and self.account.d["rewards"]["pending"]:
            pending = (f"pending reward sets (0x2125): {len(self.account.d['rewards']['pending'])}",
                       M.reward_sets(self.account.reward_elements()))
        self.log(f"client asks for pending rewards (0x2124): {'sending it' if pending else 'none'}")
        if pending:
            self.send_many([pending])

    def ev_claim_reward(self, msg):
        """0x2128 ClaimPostMatchReward: u32 set | u32 choice | u32 source | u64 instance | list items | list qty |
        list bestowal. The tutorial's reward plays its showcase movie on the client; account rewards are granted
        here (ownables 0x20B8, currencies 0x2081, ribbons 0x2095)."""
        b = msg.body
        set_did = matchend.claimed_set(b)
        choice = struct.unpack_from("<I", b, 4)[0] if len(b) >= 8 else 0
        instance = struct.unpack_from("<Q", b, 12)[0] if len(b) >= 20 else 0
        items = []
        if len(b) >= 24:
            n = struct.unpack_from("<I", b, 20)[0]
            if 0 <= n < 64 and len(b) >= 24 + 4 * n:
                items = list(struct.unpack_from("<%dI" % n, b, 24))
        self.log(f"client claimed the reward set {set_did:#x} (0x2128), instance {instance}, choice {choice:#x}")
        self.pending_reward = None
        acct = self.account
        if acct is None:
            return
        entry, changed = acct.claim(self.adata, self.roster(), instance, set_did, choice, items)
        if entry is None:
            return
        self.save_account()
        out = [(f"currency balance (0x2081)", M.currency_balance(acct.wallet["hard"], acct.wallet["soft"]))]
        if changed:
            out.append((f"ownables changed (0x20b8): {len(changed)}",
                        M.ownables(acct.ownable_items(self.roster(), self.adata, changed))))
            out += [(f"ribbon: item {d:#x} (0x2095)", M.item_fulfilled(entry["instance"], d)) for d in sorted(changed)]
        self.send_many(out)

    def _objects(self, link):
        w = self.match.world
        # 2026-10-25 (map-loading-deep-scan.md 3): the encounter's lighting key ([ics] lighting_env: encounter ->
        # key, "default"); 0 is never sent (fase3-cf: the table's default 0x08000000 is no environment record)
        table = self.ic.get("lighting_env") or {}
        env = int(str(table.get(f"0x{self.match.encounter:08X}", table.get("default", 0x10000016))), 0) or 0x10000016
        M.LIGHTING_ENV[0] = env
        if self.ic.get("champion_bundle_snap", True):
            # 2026-10-30 (tester report 14:51 video: "AGL is very far off the floor"; agl-floor-raider-pad-pct-prow.md 1):
            # the champion + player bundle (credits, XP, level, teleports) carried the champion's z as it was, up to
            # 1.44 m over the navmesh; it is put on the navmesh first ([ics] champion_bundle_snap)
            before = w.champion.pos[2]
            w.snap_to_ground(w.champion)
            if abs(w.champion.pos[2] - before) > 0.01:
                w._ground_fix_log(w.champion, before, "bundle")
        late = w.champion.sequence >= 1
        w.champion.sequence += 1
        seq = w.champion.sequence
        now = time.time()
        props = w.properties(w.champion)
        champion = M.create_object(M.CHAMPION_AGENT_ID, w.champion.class_id, now, sequence=seq,
                                   position=w.wire_position(w.champion), heading=w.champion.heading,
                                   speed=w.champion.speed, tele_seq=getattr(w.champion, "tele_seq", 1),
                                   second_seq=1 if w.in_world else 0,
                                   properties=props, **w.tilt(w.champion))   # facing_offset: a facing lock (2026-11-03)
        if w.delta_mode():
            # 2026-10-28 15:00 (tester report 2026-10-28 15:00; object-update-bundles.md 11.4): the champion's full
            # bundle; its later updates are deltas against it ([ics] object_update_mode)
            w.remember_full(w.champion, props, now)
        champion += self._champion_vitals(w)
        return champion + self._player_bundle(w, link, seq, late)

    @staticmethod
    def _champion_vitals(w):
        return M.vitals(M.CHAMPION_AGENT_ID, [(w.champion.health, w.champion.max_health),
                                              (w.champion.will, w.champion.max_will)])

    def _player_bundle(self, w, link, seq, late=True):
        """The player object's bundle of _objects: its links to the champion (link) and its properties."""
        links = {M.PROP_CONTROLLED_AGENT: M.CHAMPION_AGENT_ID, M.PROP_PLAYER_ENTITY_LINK_2: M.CHAMPION_AGENT_ID} if link else {}
        player_props = M.player_properties() + [(0x1000009C, M.KIND_INT, self.ic["team"])]
        if late:
            # from the second bundle on, as the earlier server did: the client's map manager loads the map when
            # 0x100001D3 (the encounter) changes; 2026-10-21 (tester: "the map loads wrong") it was only sent
            # after the load, and the client reported load complete at 60 %
            player_props += M.player_late_properties(self.match.encounter)
        return M.create_object(M.LOCAL_PLAYER_ID, self.ic["player_class"], time.time(), sequence=seq,
                               position=w.wire_position(w.champion), second_seq=1 if w.in_world else 0,
                               iid_properties=links, properties=player_props)

    def _link(self):
        m = self.match
        if m and m.world:
            m.linked = True
            self.send("link player -> champion", self._objects(link=True))
            if self.ic.get("advancement_handlers", True):
                # 2026-10-26 (tester: the level ring shows no XP; hud-xp-ring.md: the ring's thresholds come from
                # InqXPForLevel, which no handler answered, so 0 / 0): register the player's advancement handlers
                self.send("advancement handlers (0x9f 0x81a1000b)", M.advancement_handlers(
                    bool(self.ic.get("advancement_rpc_leading_u8", True)), bool(self.ic.get("advancement_rpc_blob4", False))))
            if m.lobby and self.ic.get("recommended_at_link", True):
                # 2026-10-25 (tester: the shop's Recommended row is empty; hud-shop-timeline-kills.md 1, C: the client
                # reads the list once while the HUD movies load, before load complete): right after the link
                self._send_recommended(m)

    def _tick(self):
        m = self.match
        if not m or not m.world:
            return False
        now = time.monotonic()
        dt = now - m.last_tick if m.last_tick else 0.0
        m.last_tick = now
        w = m.world
        if m.director and m.in_world:
            m.director.tick()
        if m.mode is not None and m.in_world and not m.mode_error:
            try:
                tick = getattr(m.mode, "tick", None)
                if tick is not None:
                    tick(dt)
                else:
                    mod = self._mode_module()
                    if mod is not None and hasattr(mod, "tick"):
                        mod.tick(dt)
            except Exception as e:
                # 2026-10-28 10:35 (tester: minions, the bot and base regen froze for the rest of the match, the victory
                # came twice): one exception stopped the whole mode layer; now it is logged with its traceback and the
                # layer stops only after [ics] mode_error_limit errors (0 = stop at the first, as before)
                m.mode_errors = getattr(m, "mode_errors", 0) + 1
                limit = int(self.ic.get("mode_error_limit", 50) or 0)
                if m.mode_errors > limit:
                    m.mode_error = True
                self.log(f"mode layer tick failed ({m.mode_errors}{', stopped for this match' if m.mode_error else ''}):"
                         f" {e!r}\n{traceback.format_exc()}")
        # 2026-10-28 15:00 (tester report 2026-10-28 15:00; object-update-bundles.md 7 / 11.4 / 12.3 a): in delta mode
        # ([ics] object_update_mode) each changed object gets World.update at today's cadence (the champion every tick it
        # changed, a bot when motion_due, a missile when it turns): a motion-only state and its changed properties, no
        # 0xBC (which removed the ids sent by 0x6 only), no player-object bundle or 0x42 with the champion's motion
        delta = w.delta_mode()
        for ent in w.tick(dt, time.time()):
            if ent is w.champion:
                if delta:
                    # force: the per-tick state was never held by a carry (bundle_hold holds labelled updates only)
                    w.update(ent, None, force=True)
                    extra = b""
                    if self.ic.get("delta_vitals_with_motion", False):
                        extra += self._champion_vitals(w)
                    if self.ic.get("delta_player_object", False):
                        extra += self._player_bundle(w, m.linked, w.champion.sequence)
                    if extra:
                        self.user.send(extra, None)
                    if self.user.closed:
                        return False
                elif not self.user.send(self._objects(m.linked), None):
                    return False
            elif getattr(ent, "bot", False) and ent.sequence > 0:
                # 2026-10-25 (bot-champions.md 3.5): a bot's movement only when its velocity changes; 22:07 (tester: a
                # dead bot slides until it respawns, then walks lying down and is invisible until it attacks): the
                # motion-only state (0x4 with only 0xB0) is not applied by the client, so the throttled update goes
                # as a full bundle unless [ics] bot_motion_only
                # 2026-10-28 15:00 (object-update-bundles.md 0.5 / 11.2: the 0xB0-only state is applied; the "invisible"
                # bot was its fog flag 0x90F, which went only in full bundles): delta mode sends the throttled state AND
                # every changed property (the fog flip of a standing bot too)
                if delta:
                    w.update(ent, None, motion=w.motion_due(ent))
                else:
                    msg = w.motion_update(ent)
                    if msg is not None:
                        self.user.send(msg if self.ic.get("bot_motion_only", False) else w.bundle(ent),
                                       w.forced_motion_label(ent))
            elif ent.kind == "missile" and self.ic.get("missile_bundle_on_turn", True):
                self._missile_motion(w, ent)
            elif delta:
                w.update(ent, None)
            else:
                self.user.send(w.bundle(ent), w.forced_motion_label(ent))
            m.last_sent = now
        if delta:
            # the idle full bundle (which removed the 0x6-only ids too) becomes a resync: the champion's movement state and
            # its properties by 0x6, every [ics] delta_resync_seconds without any update (0 = none)
            every = float(self.ic.get("delta_resync_seconds", 5.0) or 0.0)
            if m.linked and every > 0 and now - m.last_sent > every:
                m.last_sent = now
                w.resync(w.champion)
        elif m.linked and now - m.last_sent > self.cfg["timing"]["idle_resend"]:
            m.last_sent = now
            self.user.send(self._objects(True), None)
        return True

    def _missile_motion(self, w, ent):
        """2026-10-28 09:36 (tester: Grab pulls but AGL's stretched arm never shows; grab-beam.md, P suspect): a full
        bundle every tick re-created the missile and dropped its running Vfx_Active, whose beam particles are the arm.
        The client flies the object from its bundle's position, heading and speed; a new bundle goes only when its course
        turns ([ics] missile_turn_radians) or it stops, and the effect keys of [ics] missile_rebundle_scriptlets are
        played again right after it. 2026-10-28 15:00 (object-update-bundles.md 3 / 6.1, C: a bundle re-creates
        nothing, so the replay only started a second beam): in delta mode the turn goes as a motion-only state and
        nothing is replayed."""
        sig = (round(ent.heading / max(float(self.ic.get("missile_turn_radians", 0.12)), 1e-3)), ent.speed > 0)
        if getattr(ent, "motion_sig", None) == sig:
            return
        first = getattr(ent, "motion_sig", None) is None
        ent.motion_sig = sig
        if w.delta_mode():
            w.update(ent, None)
            return
        self.user.send(w.bundle(ent), None)
        if first:
            return
        for name in self.ic.get("missile_rebundle_scriptlets") or ():
            key = w.data.scriptlet_key(name)
            if key and (ent.scriptlet_keys is None or key in ent.scriptlet_keys):
                w.schedule(0.03, lambda k=key: w.scriptlet(ent, k) if ent.eid in w.entities else None)

    def ev_notice(self, msg):
        m = self.match
        if not m or not m.world:
            return NotImplemented
        if msg.body[:4] == NOTICE_LOAD_COMPLETE:
            if m.in_world:
                return
            m.in_world = m.world.in_world = True
            m.started = time.monotonic()
            self.set_phase(PLAYING, "client reports load complete")
            self.send("objects again (in world)", self._objects(True))
            m.world.vital_notices_on()
            m.world.send_camera_yaw()
            m.world.mirror_skill_scripts()
            if self.ic.get("encounter_property_event", True) and not m.lobby:
                self._encounter_property(m, "none")
            ch = m.world.champion
            if self._send_recommended(m):
                self.send("inventory (0x20e2)", M.inventory(ch.eid, ch.inventory))
            if m.lobby:
                if self.ic.get("dialog_enable_notice", True):
                    # 2026-10-23 (no announcer line played): notice 0x10000205 enables the client's dialog system
                    self.send("dialog system on (notice 0x10000205)", M.dialog_enable())
                if self.ic.get("encounter_property_event", True):
                    # after the match-start notice: the minimap's listener exists; the shop's (Upgrade manager,
                    # created at match start 0xa91e30) only later, and a bundle on an existing object does not
                    # re-broadcast, so a second pass re-creates the player once the match has started
                    self.later(float(self.ic.get("player_rebind_delay", 1.0)),
                               lambda: self._encounter_property(m, "none") if self.match is m else None, m.group)
                    late = float(self.ic.get("player_recreate_delay", 0) or 0)
                    if late > 0:
                        self.later(late, lambda: self._encounter_property(m) if self.match is m else None, m.group)
                self._start_lobby_match(m)
                cin = getattr(m, "pending_cinematic", 0)
                if cin:
                    m.pending_cinematic = 0
                    self.later(float(self.cfg["timing"].get("cinematic_delay", 5.0)),
                               lambda: self._play_cinematic(cin) if self.match is m else None, m.group)
                return
            # 2026-10-21 (tester: the map loaded wrong): the units came while the client was still loading; the
            # earlier server created the map's objects ~20 s later. [timing] units_delay after load complete.
            self.later(float(self.cfg["timing"].get("units_delay", 3.0)), self._spawn_units, m.group)
            if m.director:
                # the flow plays the intro cinematic and shows the HUD when its steps say so
                self.later(float(self.cfg["timing"].get("cinematic_delay", 5.0)), self._start_director, m.group)
                return
            if self.ic.get("show_hud", True):
                self.show_hud()
            cin = int((self.cfg.encounter(m.encounter) or {}).get("intro_cinematic", 0) or 0)
            if cin:
                self.later(float(self.cfg["timing"].get("cinematic_delay", 5.0)),
                           lambda: self._play_cinematic(cin), m.group)
            return
        if msg.body[:4] == NOTICE_CINEMATIC and len(msg.body) >= 12:
            state, did = struct.unpack_from("<II", msg.body, 4)
            self.log(f"cinematic {did:#x} state {state}")
            if state == 4:
                m.world.stop_scenes(did)
                if m.mode is not None and hasattr(m.mode, "intro_done"):
                    m.mode.intro_done()
                if (m.result is not None and not m.director
                        and not self.ic.get("restore_after_end_cinematic", False)):
                    # 2026-10-28 13:52 (tester: the score screen showed no data; timeline-kda-endscreen.md 3): the end
                    # cinematic finishes after the match-ended notice, when the client is leaving for the end page; the
                    # objects / HUD re-send only raced the teardown ([ics] restore_after_end_cinematic = true: as before)
                    self.log("end cinematic over after the match end: no objects / HUD re-send")
                    return
                self.send("objects again (after the cinematic)", self._objects(True))
                if m.world.delta_mode():
                    # 2026-10-28 15:00 (object-update-bundles.md 12.3 e): that full bundle removed the champion's 0x6-only
                    # unit flags; in delta mode nothing else would put them back ([ics] object_update_mode)
                    m.world.vital_notices_on()
                if m.director:
                    m.director.cinematic_state(did, state)
                elif self.ic.get("show_hud", True):
                    # the earlier server showed the HUD after the intro; a cinematic hides it again when it ends
                    self.send_many([(f"HUD element {e} shown (0x213d)", M.hud_element(e, 1))
                                    for e in self.data.hud_elements()])
            return
        if m.mode is not None and hasattr(m.mode, "on_notice") and len(msg.body) >= 8:
            # the match's own notices (HUD ready, timeline, team health, surrender ...) go to the mode layer
            nid, n = struct.unpack_from("<II", msg.body, 0)
            try:
                if m.mode.on_notice(nid, msg.body[8:8 + n]) is not NotImplemented:
                    return
            except Exception as e:
                self.log(f"mode layer on_notice failed: {e!r}")
        if msg.body[:4] == NOTICE_SURRENDER and m.lobby and m.mode is None:
            yes = len(msg.body) >= 9 and msg.body[8] != 0          # u32 notice | u32 length | u8 vote
            self.log(f"surrender vote: {'yes' if yes else 'no'} (notice 0x10000454)")
            if yes:
                self.match_result(int(self.ic.get("enemy_team", 2)), stats={"surrendered": True})
            return
        return NotImplemented

    def _encounter_property(self, m, mode=None):
        """0x100001D3 (the encounter) on the player as a CHANGE: the shop catalogue (0xa91670 -> 0xa908f0) and the map
        load (0xa6a8e0 -> LoadMap 0xa4c2c0: minimap, map info, fog) listen for it. 2026-10-23 13:14 / 15:01 (diag
        --shop: never reached): those listeners attach to the player object only on a key-0x26 broadcast of its
        bundle (0x69bd00 from 0x64bd30 / 0x64dac0), and ours came while the client was loading, before the managers
        existed. [ics] player_rebind: "bundle" = the player (and champion) bundle again first, "recreate" = the player
        object removed (0x3) and created anew, "none" = only the property events."""
        mode = mode or str(self.ic.get("player_rebind", "none"))
        out = []
        if mode == "recreate":
            out.append(("player object removed (0x3, rebind)", M.remove_object(M.LOCAL_PLAYER_ID)))
        if mode in ("bundle", "recreate"):
            out.append(("player + champion again (rebind the map / shop listeners)", self._objects(True)))
        # 2026-10-23 15:30 (diag: LoadMap ran with Tutorial 1's encounter, the value left from an earlier match; the
        # listener 0xa6a8e0 probably gets a change's PREVIOUS value): encounter, 0, encounter loads it either way
        for value in (m.encounter, 0, m.encounter):
            out.append((f"encounter {value:#x} on the player (0x100001d3, 0x6)",
                        M.set_property(M.LOCAL_PLAYER_ID, 0x100001D3, M.KIND_DID, value)))
        self.send_many(out)
        if mode in ("bundle", "recreate") and m.world is not None and m.world.delta_mode():
            # 2026-10-28 15:00 (tester report 2026-10-28 15:00; object-update-bundles.md 12.3 e): that champion bundle
            # removed its 0x6-only unit flags, which no per-tick bundle / labelled send re-toggles in delta mode ([ics]
            # object_update_mode)
            m.world.vital_notices_on()

    def _start_lobby_match(self, m):
        """A lobby match is in the world: the HUD, then the mode layer runs it; without one the stub ends it after
        pvp_stub_seconds."""
        if self.ic.get("show_hud", True):
            # 2026-10-23 14:00 (tester: the HUD has no backgrounds): the panels a tutorial-type encounter starts hidden
            # (BaseHudElement.SetInitialVisibilityBasedOnEncounter: 11 CharacterPanel, 13, 16 StatsPanel, 29, 33, 44 ...)
            # are shown too ([ics] lobby_hud_extra)
            extra = [int(e) for e in self.ic.get("lobby_hud_extra") or ()]
            self.show_hud(sorted(set(self.data.hud_elements()) | set(extra)))
        start = float(self.ic.get("announcer_test_on_start", 0) or 0)
        if start > 0:
            # 2026-10-23 12:14 (no chat message reached the server in the match): the announcer test plays by itself
            self.later(start, lambda: self._chat_command("/anunciador todos") if self.match is m else None, m.group)
        if m.mode is None:
            if not hasattr(self, "_warned_mode"):
                self._warned_mode = True
                self.log("no mode layer (ics/match): the lobby match is a free walk on the map")
            if self.ic.get("spawn_layout", True):
                self.later(float(self.cfg["timing"].get("units_delay", 3.0)), self._spawn_units, m.group)
            stub = float(self.ic.get("pvp_stub_seconds", 0) or 0)
            if stub > 0:
                win = int(self.ic["team"]) if str(self.ic.get("pvp_stub_winner", "me")) == "me" \
                    else int(self.ic.get("enemy_team", 2))
                self.later(stub, lambda: self.match_result(win) if self.match is m else None, m.group)

    def _play_cinematic(self, cin):
        m = self.match
        if not m or not m.world:
            return
        # 2026-10-22 14:45 (tester: two Batmans in the cinematics): the scene's "player" actor was a second Batman
        # beside ours; the champion is bound to it (flags bit 1 + {0, champion}) and the client hides the world's
        # Characters while it plays (bit-3 PerceivedType mask), as client-cinematics-matchend.md 1.2-1.4 reads
        bind = bool(self.ic.get("cinematic_bind_champion", True))
        hide = int(self.ic.get("cinematic_hide_types", 0x8) or 0)
        bindings = [(0, M.CHAMPION_AGENT_ID)] if bind else []
        if bind and self.ic.get("cinematic_bind_allies", True):
            # 2026-10-29 (tester report 2026-10-29 15:30: on Gotham Heights only the player's champion plays the intro
            # line-up animation; gh-ca-floor-spawn.md 4): the PvP intros (GH 0x35000023, CC 0x35000020) have five
            # "needs binding" actors, ThePlayer (key 1) and Player01..04 (actor variables 0x10000001..4); an unbound
            # one is skipped. With flags bit 1 and the solo check (0xa9c610, A = 0) only the local champion's entry is
            # rewritten (key 1), the others keep the key sent: the allied bots go out as 0x10000001.. in lobby order
            # (false = only the champion, as before)
            w, mode = m.world, getattr(m, "mode", None)
            team = getattr(w.champion, "team", None) if w.champion is not None else None
            allies = [c for c in (mode.champions() if mode is not None and hasattr(mode, "champions") else ())
                      if c is not w.champion and team is not None and getattr(c, "team", None) == team]
            bindings += [(0x10000001 + k, c.eid) for k, c in enumerate(allies[:4])]
        msg = M.cinematic(cin, flags=M.CINEMATIC_FLAG_BIND_CHECK if bind else None,
                          bindings=bindings, hide_types=hide)
        self.send(f"cinematic {cin:#x} (0x20f5)" + (f", {len(bindings)} bound" if bind else "")
                  + (f", hides PerceivedType {hide:#x}" if hide else ""), msg)
        info = self.data.encounter(m.encounter)
        if info.get("layout_pack"):
            m.world.play_scenes(cin, info["layout_pack"])

    def _start_director(self):
        m = self.match
        if not m or not m.director:
            return
        jump = str(self.ic.get("director_start", "") or "")
        if jump and m.director.jump(jump):
            return
        m.director.start()

    def _spawn_units(self):
        m = self.match
        if not m or not m.world:
            return
        enc = self.encounter_info()
        names = getattr(self._flow(m), "INITIAL", None) if m.director else None
        for ent in m.world.spawn_layout(enc, names):
            self.send(f"spawn {ent.name} ({ent.class_id:#x})", m.world.bundle(ent))
            m.world.vitals(ent)
            m.world.start_unit_scripts(ent)
        props = [e for e in m.world.entities.values() if e.kind in ("prop", "unit")]
        if props:
            # after the objects exist on the client (its script component is built with the object)
            self.later(float(self.cfg["timing"].get("prop_scriptlet_delay", 1.0)),
                       lambda: [m.world.initial_scriptlets(e) for e in props], m.group)

    def ev_script_rpc(self, msg):
        """0x9F script RPC from the client: u32 message | u32 n | n bytes (docs/re-notes/emotes.md). Only the
        emote (0x81970006, blob = the emote record DID, written by CEmoteSystem 0x28F:1 for Alt+Numpad1-5) is played;
        anything else is logged."""
        b = msg.body
        if len(b) < 5:
            return NotImplemented
        # 2026-10-24 00:55 (tester's capture: 06 00 97 81 | 04 00 00 00 | 3f 02 00 40): the body is u32 message | u32 n |
        # blob, without the leading u8 the notes expected; both forms are read
        off = 1 if b[0] == 0 and len(b) > 4 and b[4] & 0x80 else 0
        message = struct.unpack_from("<I", b, off)[0]
        blob = b[off + 8:] if len(b) >= off + 8 else b""
        ic = self.ic
        m = self.match
        if message == 0x81910003 and len(blob) >= 16:
            # 2026-10-30 log audit (tester run 11:05-11:23, scorecard-panel-turret-head.md 4): the client's RankSkill
            # stub (client-scripts-and-ui.md 1.7: u32 new rank | u32 slot | u64 agent) goes ~130 ms before the patched
            # rank request that ics applies; logged as such instead of "not handled"
            rank, slot, agent = struct.unpack_from("<IIQ", blob, 0)
            w = m.world if m else None
            why = w.rank_refusal(w.champion, slot) if w and w.champion else None
            self.log(f"script rpc RankSkill (0x81910003): slot {slot} rank {rank} agent {agent:#x} "
                     + (f"(the server will refuse it: {why})" if why else "(applied by the patched rank request)"))
            return
        if message != 0x81970006 or not m or not m.world or not ic.get("emotes", True):
            self.log(f"script rpc {message:#x} body {b.hex()} (0x9f): not handled")
            return
        emotes = {int(str(k), 0): v for k, v in (ic.get("emote_graph_events") or {}).items()}
        # the record DID is the blob's u32; scan for it in case the stream adds a type tag
        did = next((v for o in range(0, max(0, len(blob) - 3)) for v in [struct.unpack_from("<I", blob, o)[0]]
                    if v in emotes), None)
        if did is None:
            self.log(f"emote (0x9f) with unknown record: blob {blob.hex()}")
            return
        self._emote(did)

    EMOTE_WORDS = {"joke": 0x40000241, "broma": 0x40000241, "taunt": 0x40000240, "provocar": 0x40000240,
                   "laugh": 0x40000242, "reir": 0x40000242, "dance": 0x4000023F, "bailar": 0x4000023F,
                   "oath": 0x40000EE6, "juramento": 0x40000EE6}

    def _emote(self, did):
        """Play the emote record's graph event (or scriptlet) on the champion ([ics] emote_graph_events)."""
        m = self.match
        if not m or not m.world or m.world.champion is None:
            return False
        emotes = {int(str(k), 0): v for k, v in (self.ic.get("emote_graph_events") or {}).items()}
        how = emotes.get(did)
        if how is None:
            return False
        w = m.world
        ch = w.champion
        if self.ic.get("emote_stops_movement", True) and (ch.dest is not None or ch.attack_target is not None):
            # 2026-10-28 13:5x (tester: an emote during a move slides the champion, playing the emote, to the point): the
            # emote stops the move / attack first, as a stop order would ([ics] emote_stops_movement)
            ch.dest, ch.path, ch.speed, ch.attack_target = None, [], 0.0, None
            ch.pending_move = None
            w.update(ch, f"{ch.name} stops for an emote")
        if isinstance(how, str) and not how.lower().startswith("0x"):
            w.scriptlet(ch, how, f"{ch.name}: emote {how} (0x8d)")
        else:
            w.graph_event(ch, int(str(how), 0), f"{ch.name}: emote {did:#x} (graph event {int(str(how), 0):#x})")
        return True

    def ev_order(self, msg):
        """0x20EE: u32 command | u32 ability | u64 target IID | Position | u8."""
        m = self.match
        if not m or not m.world or len(msg.body) < 16:
            return NotImplemented
        w = m.world
        ch = w.champion
        command, ability = struct.unpack_from("<II", msg.body, 0)
        target_id = struct.unpack_from("<Q", msg.body, 8)[0]
        target = w.entities.get(target_id)
        point = None
        if len(msg.body) >= 17:
            point = w.from_wire(parse_client_position(msg.body, 16))
        if time.time() < getattr(ch, "down_until", 0.0):
            self.log("order ignored: Batman is down (knockdown)")
            return
        if not ch.alive and self.ic.get("dead_orders_ignored", True):
            # tester report 2026-10-29 12:45 (AGL slid while falling: the client gates orders on LifeState 4 only once it
            # applies the death state, so two moves came 65-75 ms after the death bundle; unit-death-slide-levelup.md 2):
            # a dead champion's orders are dropped ([ics] dead_orders_ignored)
            self.log(f"order ignored: {ch.name} is dead (command {command})")
            return
        if command in (CMD_ATTACK, CMD_SKILL) and (ability or command == CMD_SKILL):
            self.log(f"skill order: slot {ability}, target {target or hex(target_id)}, point "
                     f"{point and tuple(round(v, 1) for v in point)}")
            ch.attack_target = None
            if ch.dest is not None:
                ch.dest, ch.speed = None, 0.0
            w.cast(ch, ability, target, point)
            return
        if command == CMD_ATTACK:
            if target is not None and target.alive and target.health is not None:
                ch.attack_target = target
                self.log(f"attack {target.name} ({target.health}/{target.max_health})")
            else:
                self.log(f"attack order on {target_id:#x}: not attackable")
            return
        if command == CMD_USE:
            # 2026-10-25 16:29 (unhandled.log: two orders with command 1 on a drop pad): use a usable object
            if target is None or not w.use_object(ch, target):
                self.log(f"use order on {target.name if target else hex(target_id)}: nothing to use")
            return
        if command == CMD_STOP:
            ch.attack_target, ch.dest, ch.speed, ch.path = None, None, 0.0, []
            if w.delta_mode():
                # 2026-10-28 15:00 (object-update-bundles.md 11.4; [ics] object_update_mode): the stop as an update (a
                # motion-only stop state), never held by a carry, as the champion + player bundles it replaces
                w.update(ch, "stop", force=True)
            else:
                self.send("stop", self._objects(m.linked))
            return
        if command == CMD_MOVE and point is not None:
            near = self._click_assist(w, ch, point, target)
            if near is not None:
                ch.attack_target = near
                self.log(f"attack {near.name} ({near.health}/{near.max_health}) [click assist: move order "
                         f"{(target.name if target else hex(target_id))} at ({point[0]:.1f}, {point[1]:.1f})]")
                return
        if command in (CMD_MOVE, CMD_ATTACK_MOVE):
            ch.attack_target = None
            if point is None:
                self.log(f"move order not understood: {msg.body.hex()}")
                return
            point = self._pre_start_leash(m, point)
            if w.walk_to(ch, point):
                self.log(f"move -> ({point[0]:.1f}, {point[1]:.1f}, {point[2]:.1f})"
                         + (f" ({len(ch.path) + 1} segments)" if ch.path else ""))
            return
        return NotImplemented

    def _click_assist(self, w, ch, point, picked):
        """2026-10-29 (tester report 2026-10-29 18:31: no hover outline on enemy minions / champions, several right
        clicks needed to attack; ca-fog-stealth-hover.md 3, C traffic): of 1 463 move orders (0x20EE command 4) in that
        run 107 carried the client's hover pick = our own champion (53) or an ALLIED minion / turret, the rest none; the
        client's pick (0xA81B30) found the enemy under the cursor only with the exact render ray. A move order whose
        ground point lies within [ics] click_assist_radius (m by kind) of a visible enemy unit / champion, and whose
        pick was not an enemy, is taken as the attack on the nearest one ({} = off, every move order moves)."""
        radii = self.ic.get("click_assist_radius") or {}
        if not radii or (picked is not None and picked is not ch and getattr(picked, "team", ch.team) != ch.team):
            return None
        best, best_d = None, None
        for e in list(w.entities.values()):
            r = float(radii.get(getattr(e, "kind", ""), 0) or 0)
            if (r <= 0 or e is ch or not e.alive or e.health is None or e.team in (0, ch.team)
                    or getattr(e, "hidden", False)):
                continue
            d = math.hypot(e.pos[0] - point[0], e.pos[1] - point[1])
            if d <= r and (best_d is None or d < best_d):
                best, best_d = e, d
        return best

    def _pre_start_leash(self, m, point):
        """2026-10-25 16:12 (tester's video 11:50: on Gotham Heights, which has no base gates, the player walked to a
        capture point during the countdown): before the match starts a move order stops [ics] pre_start_leash m from
        the champion's start point on maps without gates (0 = off)."""
        mode = getattr(m, "mode", None)
        leash = float(self.ic.get("pre_start_leash", 0) or 0)
        blockers = self.ic.get("prop_blockers") or {}
        blocking = any(f"0x{g.world_state:08X}" in blockers for g in (getattr(mode, "gates", None) or ()))
        if leash <= 0 or mode is None or getattr(mode, "begun", True) or blocking:
            return point                       # a gate that blocks the way holds the player in already
        home = m.world.spawn_pos
        dx, dy = point[0] - home[0], point[1] - home[1]
        d = math.hypot(dx, dy)
        if d <= leash:
            return point
        return [home[0] + dx * leash / d, home[1] + dy * leash / d, point[2]]

    def ev_conversation_done(self, msg):
        """0x2140: u32 instance - the client has played a conversation (2026-10-22 09:13: one per 0x2001 instance,
        in order, as each ended)."""
        if len(msg.body) < 4:
            return NotImplemented
        inst = struct.unpack_from("<I", msg.body, 0)[0]
        self.log(f"conversation instance {inst:#x} finished (0x2140)")
        if self.match and self.match.world and self.ic.get("conversation_done_event", True):
            self.match.world.emit("conversation_done", instance=inst)

    def ev_preference(self, msg):
        """0x216E: str8 name | wstr value | u32 kind (0x10000C33 bool, 0x10000A0E number, 0x100009ED string); kept
        on the account and sent back with 0x216A at the next login."""
        try:
            b = msg.body
            n, pos = read_compact(b, 0)
            name = b[pos:pos + n].decode("ascii")
            pos += n
            k, pos = read_compact(b, pos)
            value = b[pos:pos + 2 * k].decode("utf-16-le")
            pos += 2 * k
            kind = struct.unpack_from("<I", b, pos)[0] if len(b) >= pos + 4 else 0
        except (IndexError, UnicodeDecodeError, struct.error):
            return NotImplemented
        self.log(f"client preference {name} = {value}" + (f" (kind {kind:#x})" if kind else ""))
        if self.account is not None:
            self.account.set_preference(name, value, kind)
            self.save_account()
        if self.match and self.match.world:
            self.match.world.emit("preference", name=name, value=value)

    def _shop_body(self, body, n):
        """The shop events' fields (u32 x n | u32 handle seq | u64 handle iid), with or without a leading u8 0."""
        size = 4 * n + 12
        if len(body) == size + 1 and body[0] == 0:
            body = body[1:]
        if len(body) < size:
            return None
        return struct.unpack_from("<" + "I" * n + "IQ", body, 0)

    def _shop_answer(self, m, seq, iid, label):
        ch = m.world.champion
        m.world.refresh_champion(f"credits {ch.gold:.0f}, {sum(1 for d in ch.inventory if d)} items")
        m.world.vitals(ch)
        self.send_many([(f"inventory {' '.join(hex(d) for d in ch.inventory)} (0x20e2)", M.inventory(ch.eid, ch.inventory)),
                        (f"{label}: shop unlocked (0x2086)", M.shop_transaction_done(seq, iid))])

    def ev_purchase(self, msg):
        """0x208B purchase: u32 artifact | handle (u32 seq | u64 iid). Validated here: the client sends it whatever
        its own price check says (shop-items-inventory.md 3.1)."""
        m = self.match
        f = self._shop_body(msg.body, 1)
        if not m or not m.world or not m.shop or f is None:
            return NotImplemented
        did, seq, iid = f
        ok = m.shop.buy(m.world.champion, did)
        self._shop_answer(m, seq, iid, f"buy {did:#x} " + ("done" if ok else "refused"))
        if ok and self.ic.get("recommended_follow_inventory", True):
            self._send_recommended(m)

    def _send_recommended(self, m):
        """0x2078: the champion's default loadout's buys, in order (0x10000478), the shop's Recommended panel.
        2026-10-24 23:20 (tester: the Recommended panel must go away once its starting item is bought): re-sent after
        every purchase without the items already held ([ics] recommended_follow_inventory)."""
        ch = m.world.champion
        rec = list(self.data.loadout(ch.class_id)["artifacts"] or [])
        if not rec:
            return False
        if self.ic.get("recommended_follow_inventory", True):
            held = {d for d in ch.inventory if d}
            rec = [d for d in rec if d not in held]
        self.send(f"recommended upgrades: {len(rec)} (0x2078)", M.recommended_upgrades(ch.eid, rec))
        return True

    def ev_sell(self, msg):
        """0x20A7 sale: u32 artifact | u32 slot 0..5 | handle."""
        m = self.match
        f = self._shop_body(msg.body, 2)
        if not m or not m.world or not m.shop or f is None:
            return NotImplemented
        did, slot, seq, iid = f
        ok = m.shop.sell(m.world.champion, did, slot)
        self._shop_answer(m, seq, iid, f"sell {did:#x} " + ("done" if ok else "refused"))

    def ev_skill_events(self, msg):
        """0x20EA (sender 0x88b280 <- 0xa23510, from the order dispatcher 0xa85da0 for skills with 0x10000A46):
        u32 slot | list<u32> events; each event goes to that slot's skill script (e.g. 0x10000023, P: the press /
        release of a held skill). 2026-10-23: 441 of them were dropped in one match."""
        m = self.match
        filtered = self.ic.get("skill_client_events_filtered", True) and self.ic.get("script_accept_filter", True)
        if not m or not m.world or len(msg.body) < 8 or not (self.ic.get("skill_client_events", True) or filtered):
            return NotImplemented
        slot, n = struct.unpack_from("<II", msg.body, 0)
        events = list(struct.unpack_from(f"<{min(n, (len(msg.body) - 8) // 4)}I", msg.body, 8))
        ch = m.world.champion
        inst = ch.skill_insts.get(slot) if ch else None
        if inst is None:
            self.log(f"skill events {[hex(e) for e in events]} for slot {slot}: no script there")
            return
        for ev in events:
            m.world.raise_skill_event(ch, slot, ev)

    def ev_ping(self, msg):
        """0x2136 map ping: f32 x | f32 y | u64 arg | u32 type. The patched client sends a skill's "+" as type
        'RANK' with the slot in arg; HUD refreshes ask for every slot within a few ms (ignored)."""
        m = self.match
        if not m or not m.world or len(msg.body) < 20:
            return NotImplemented
        if struct.unpack_from("<I", msg.body, 16)[0] != RANK_SKILL_MAGIC:
            x, y = struct.unpack_from("<ff", msg.body, 0)
            target, ptype = struct.unpack_from("<QI", msg.body, 8)
            self.log(f"map ping at ({x:.1f}, {y:.1f}) type {ptype:#x}")
            if self.ic.get("ping_echo", True):
                # 2026-10-23 (tester: pings are not shown): the echo is 0x2137 with the client's own fields
                self.send(f"ping at ({x:.1f}, {y:.1f}) (0x2137)",
                          M.ping_echo(M.CHAMPION_AGENT_ID, x, y, target, ptype))
            return
        slot = struct.unpack_from("<Q", msg.body, 8)[0]
        now = time.monotonic()
        prev, _ = m.rank_ping
        m.rank_ping = (now, slot)
        if now - prev < RANK_BURST_GAP:
            return
        if not m.world.rankable(slot) and not self.ic.get("rank_refused_refresh", True):
            return                         # the fase3-ir behaviour: dropped without a word

        def decide(t=now):
            if m.rank_ping[0] != t and m.rank_ping[0] - t < RANK_BURST_GAP:
                return                     # the start of a HUD refresh burst
            # 2026-10-30 (tester: the R's "+" at level 19 did nothing): a lone request the server refuses is logged
            # with its reason and the rank state goes again (World.refuse_rank), instead of being dropped silently
            m.world.rank_skill(slot)
        self.later(RANK_BURST_GAP * 1.5, decide, m.group)

    def ev_left_world(self, msg):
        m = self.match
        self.log("client left the match world (0x12d)")
        if self.ic.get("encounter_cleared_at_end", True):
            # so the next match never starts from this one's value (the map / shop listeners act on changes)
            self.send("encounter cleared on the player (0x100001d3 = 0, 0x6)",
                      M.set_property(M.LOCAL_PLAYER_ID, 0x100001D3, M.KIND_DID, 0))
        lobby_match = bool(m and m.lobby)
        self.end_match("the client left the match")
        if lobby_match and self.ic.get("exit_lobby_after_match", False):
            self.send("exit lobby (0x2021)", M.exit_lobby(self.ic["room_id"]))
        delay = float(self.ic.get("menu_refresh_after_match", 3.0) or 0.0)
        if delay > 0:
            # 2026-10-22 14:11: the menu built after a match had no encounter data (see [ics] queue_flags)
            self.later(delay, lambda: self._menu_refresh("back from a match"))

    # ---- account screens ---------------------------------------------------------------------------------------
    def ev_request_amplifier_sets(self, msg):
        """0x20BA UI_RequestAllAmplifierSets -> 0x2090 (full-account-social.md 1.4)."""
        if self.account is None:
            return NotImplemented
        self.send(f"amplifier sets (0x2090): {len(self.account.amplifier_sets())}",
                  matchend.amplifier_sets_msg(self.account))

    def _store_keys(self):
        """[ics] store_boutique_currency_keys: SC / HC prices and the client's currency (store-fix.md 3)."""
        return bool(self.ic.get("store_boutique_currency_keys", True))

    def store_price(self, ct, wallet):
        """The price of a store item of ContentType ct in a wallet: "soft" = Merits ([ics] store_prices), "hard" =
        Crisis Coins (store_prices_hc, only with store_boutique_currency_keys). 0 = not sold in that currency."""
        key = STORE_PRICE_KEYS.get(ct)
        if key is None or wallet not in ("soft", "hard") or (wallet == "hard" and not self._store_keys()):
            return 0
        table = self.ic.get("store_prices" if wallet == "soft" else "store_prices_hc") or {}
        return max(0, int(table.get(key, 0) or 0))

    def legacy_store_wallet(self):
        """fase3-ie: every store price is in [ics] store_currency's wallet."""
        return "soft" if str(self.ic.get("store_currency", "Merits")).lower().startswith("merit") else "hard"

    def _boutique(self):
        """{boutique id: (DID, ContentType, Merit price)} of what the store sells: a price in [ics] store_prices or
        (store_boutique_currency_keys) store_prices_hc; an item sold for Crisis Coins only has Merit price 0."""
        out = {}

        def add(did, ct):
            soft = self.store_price(ct, "soft")
            if soft or self.store_price(ct, "hard"):
                out[BOUTIQUE_BASE | did] = (did, ct, soft)
        for did, ct in self.adata.amplifiers().items():
            add(did, ct)
        for c in self.roster():
            add(c["variant"], A.CT_CHARACTER)
            for s in c.get("costume_info", []):
                add(s["variant"], A.CT_SKIN)
        add(A.AMP_SLOT_ITEM, A.CT_AMP_SLOT)
        return out

    def boutique_entries(self):
        """0x2107's (boutique id, DID, currency name, price) for augments, mods and the set slot. With [ics]
        store_boutique_currency_keys: an "SC" entry (Merits) and an "HC" entry (Crisis Coins) per item, each when that
        price is > 0, under one boutique id (BoutiqueDataManager keeps one BoutiqueData per DID and a price only for
        those two names, case ignored: store-fix.md 3.1, C); else the fase3-ie store_currency name with the Merit
        price."""
        items = [(bid, did, ct, soft) for bid, (did, ct, soft) in sorted(self._boutique().items())
                 if ct in (A.CT_AUGMENT, A.CT_MOD, A.CT_AMP_SLOT)]
        if not self._store_keys():
            cur = str(self.ic.get("store_currency", "Merits"))
            return [(bid, did, cur, soft) for bid, did, _ct, soft in items if soft]
        out = []
        for bid, did, ct, soft in items:
            if soft:
                out.append((bid, did, "SC", soft))
            hard = self.store_price(ct, "hard")
            if hard:
                out.append((bid, did, "HC", hard))
        return out

    def ev_request_boutique(self, msg):
        """0x2106 UI_RequestAllAmplifierBoutiqueData (str8 = the client language, store-fix.md 3.1) -> 0x2107."""
        entries = self.boutique_entries()
        self.send(f"amplifier boutique (0x2107): {len(entries)} prices", M.amplifier_boutique(entries))

    def _parse_purchase(self, b):
        """0x210E: u64 boutique | u32 DID | str8 currency | u32 price | str8."""
        bid, did = struct.unpack_from("<QI", b, 0)
        n, pos = read_compact(b, 12)
        cur = b[pos:pos + n].decode("ascii", "replace")
        pos += n
        price = struct.unpack_from("<I", b, pos)[0] if len(b) >= pos + 4 else 0
        return bid, did, cur, price

    def ev_store_purchase(self, msg):
        """0x210E UI_PurchaseContextualItem (store-fix.md 3.2) -> 0x210C success (+ 0x20B8, 0x2081, 0x2090 for a set
        slot) / 0x210D error. Paid at the server's price from the wallet of the client's currency ("SC" Merits, "HC"
        Crisis Coins). A different price (0xFFFFFFFF: the client had none) follows [ics] store_price_mismatch, since no
        UI listens to 0x210F (store-fix.md 3.3). store_boutique_currency_keys = false: the fase3-ie purchase
        (store_currency's wallet, the Merit price, 0x210F then 0x2110 confirm / 0x2111 cancel)."""
        try:
            bid, did, cur, price = self._parse_purchase(msg.body)
        except (struct.error, IndexError):
            return NotImplemented
        boutique = self._boutique()
        item = boutique.get(bid) or next((v for v in boutique.values() if v[0] == did), None)
        keys = self._store_keys()
        if keys:
            wallet = STORE_WALLETS.get(cur.strip().lower())
            expected = self.store_price(item[1], wallet) if item is not None and wallet else 0
        else:
            wallet, expected = self.legacy_store_wallet(), (item[2] if item is not None else 0)
        self.log(f"store purchase {did:#x} for {price} {cur} -> {wallet} {expected} (0x210e)")
        if item is None or not expected:
            why = "not sold" if item is None else f"not sold for {cur!r}"
            self.log(f"store purchase {did:#x} refused: {why} (0x210d)")
            self.send(f"purchase error: {why} (0x210d)", M.purchase_error(bid))
            return
        if price != expected:
            mode = str(self.ic.get("store_price_mismatch", "error") or "error").lower() if keys else "changed"
            if mode == "changed":
                self.pending_orders[bid] = (item, wallet, expected)
                self.send(f"purchase price changed {price} -> {expected} (0x210f)",
                          M.purchase_price_changed(bid, did, cur, price, bid, expected))
                return
            if mode != "accept":
                entries = self.boutique_entries()
                self.log(f"store purchase {did:#x} refused: price {price} is not {expected} (0x210d + 0x2107)")
                self.send_many([(f"purchase error: price {price} is not {expected} (0x210d)", M.purchase_error(bid)),
                                (f"amplifier boutique again (0x2107): {len(entries)} prices",
                                 M.amplifier_boutique(entries))])
                return
        self._complete_purchase(bid, item, wallet, expected)

    def _complete_purchase(self, bid, item, wallet=None, price=None):
        """Pay and grant one store item: 0x210C, 0x20B8 (changed items), 0x2081, the 0x2095 ribbon ([ics]
        store_purchase_ribbon) and 0x2090 for a set slot; 0x210D when every set slot is owned or the wallet is short.
        wallet "soft" / "hard" and price: the client's currency and the server's price in it; None = the fase3-ie
        charge (store_currency's wallet, the Merit price)."""
        did, ct, soft = item
        if wallet is None:
            wallet = self.legacy_store_wallet()
        if price is None:
            price = soft
        acct = self.account
        if (acct is not None and ct == A.CT_AMP_SLOT
                and acct.d["max_amplifier_sets"] >= int(self.ic.get("amplifier_set_max", 12) or 0)):
            self.log(f"store purchase {did:#x} refused: every set slot owned (0x210d)")
            self.send("purchase error: every set slot owned (0x210d)", M.purchase_error(bid))
            return False
        if acct is None or not acct.spend(wallet, price):
            self.log(f"store purchase {did:#x} refused: insufficient funds ({wallet} {price}) (0x210d)")
            self.send(f"purchase error: insufficient funds ({wallet} {price}) (0x210d)",
                      M.purchase_error(bid, M.PURCHASE_INSUFFICIENT_FUNDS))
            return False
        changed = acct.grant(did, 1, self.adata, self.roster())
        self.save_account()
        self.log(f"store purchase done: {did:#x} for {price} {wallet}; Merits {acct.wallet['soft']}, Crisis Coins "
                 f"{acct.wallet['hard']} (0x210c)")
        batch = [(f"purchase done: {did:#x} for {price} {wallet} (0x210c)", M.purchase_success(bid)),
                 (f"ownables changed (0x20b8)", M.ownables(acct.ownable_items(self.roster(), self.adata,
                                                                             changed or {did}))),
                 ("currency balance (0x2081)", M.currency_balance(acct.wallet["hard"], acct.wallet["soft"]))]
        if self.ic.get("store_purchase_ribbon", False):
            # fase3-ie: key = the DID, icon = the item's own DID, no name (store-fix.md 7.2: an empty ribbon)
            batch.append((f"ribbon: item {did:#x} (0x2095)", M.item_fulfilled(bid & 0xFFFFFFFF, did)))
        self.send_many(batch)
        if ct == A.CT_AMP_SLOT:
            # 2026-10-28 (store-amplifiers.md): one more set slot -> the list again (total + 1, a new empty set)
            self.send(f"amplifier sets (0x2090): {acct.d['max_amplifier_sets']} slots", acct.amplifier_sets_msg())
        return True

    def ev_store_confirm(self, msg):
        """0x2110 UI_ConfirmContextualPurchase (u64 | (u64 boutique, u32 DID, str8, u32, str8, u32 final)): after a
        0x210F ([ics] store_price_mismatch = "changed"); this UI never sends it (store-fix.md 3.3)."""
        if len(msg.body) < 20:
            return NotImplemented
        bid = struct.unpack_from("<Q", msg.body, 8)[0]
        pending = self.pending_orders.pop(bid, None)
        item, wallet, price = pending if pending else (self._boutique().get(bid), None, None)
        self.log(f"store purchase confirmed (0x2110): {bid:#x}")
        if item is None:
            self.send("purchase error (0x210d)", M.purchase_error(bid))
            return
        self._complete_purchase(bid, item, wallet, price)

    def ev_store_cancel(self, msg):
        """0x2111 UI_CancelContextualPurchase."""
        bid = struct.unpack_from("<Q", msg.body, 8)[0] if len(msg.body) >= 16 else 0
        self.pending_orders.pop(bid, None)
        self.log(f"store purchase cancelled (0x2111): {bid:#x}")

    def ev_web_ticket(self, msg):
        """0x0095 (empty, dest 0x0600000000000415): sent only by the web-ticket listener 0x420B90 right after it
        answered the Store screen's UI_RequestWebTicket itself, so one per SHOP open (store-fix.md 2.1, C). Its answer
        would be event 0xC2 (destination object O); the store page needs no ticket: one log line, no answer."""
        self.log("web ticket request (0x95): store screen opened (no 0xC2 sent: the store page needs no ticket)")

    def ev_save_amplifier_set(self, msg):
        """0x20FC SaveAmplifierSet: the set struct -> 0x20C7 (stored) or 0x2052 (error)."""
        acct = self.account
        try:
            b = msg.body
            slot, _sid, champion = struct.unpack_from("<IQI", b, 0)
            pos = 16
            mode = b[pos]
            pos += 1
            if mode == 1:
                n, pos = read_compact(b, pos)
                pos += 2 * n
            else:
                pos += 8
            pos += 1
            nv, pos = read_compact(b, pos)
            n, pos = read_compact(b, pos)
            name = b[pos:pos + 2 * n].decode("utf-16-le")
            pos += 2 * n
            icon = struct.unpack_from("<I", b, pos)[0]
            pos += 4
            k, pos = read_compact(b, pos)
            amps = list(struct.unpack_from("<%dI" % k, b, pos)) if k else []
        except (IndexError, struct.error, UnicodeDecodeError):
            return NotImplemented
        self.log(f"save amplifier set {slot} '{name}' for {champion:#x}: {' '.join(hex(a) for a in amps)}")
        owned = self.adata.amplifiers()
        bad = [a for a in amps if a and a not in owned]
        dup = len([a for a in amps if a]) != len({a for a in amps if a})
        if acct is None or len(name) > 21 or bad or dup:
            err = M.AMP_NAME_TOO_LARGE if len(name) > 21 else M.AMP_SAVE_FAILED
            self.send(f"amplifier set error {err:#x} (0x2052)", M.amplifier_set_error(err))
            return
        entry = acct.save_amplifier_set(slot, champion, name, icon, amps)
        if entry is None:
            self.send("amplifier set error: no free slot (0x2052)", M.amplifier_set_error(M.AMP_SAVE_FAILED))
            return
        self.save_account()
        self.send(f"amplifier set {entry['slot']} saved (0x20c7)",
                  M.amplifier_set_saved(M.amplifier_set(entry["slot"], entry["id"], champion, name, icon,
                                                        entry["amplifiers"])))

    def ev_set_protector_icon(self, msg):
        """0x2093 UI_SetProtectorIcon: u32 icon | u32 index -> 0x2154."""
        if len(msg.body) < 8 or self.account is None:
            return NotImplemented
        icon, index = struct.unpack_from("<II", msg.body, 0)
        if icon and self.ic.get("validate_protector_icons", True):
            # 2026-10-25 (profile-icons.md, C list: record 0x48000803 / 0x10000848): only an icon the picker offers
            known = set(self.adata.protector_icons()) if self.adata is not None else set()
            if known and icon not in known:
                self.log(f"protector icon {icon:#x} refused: not an icon item")
                icon = self.account.d["profile"]["icons"][index] if 0 <= index < 5 else 0
        if 0 <= index < 5:
            self.account.d["profile"]["icons"][index] = icon
            self.save_account()
        self.log(f"protector icon {index} = {icon:#x}")
        from icserver import scorecard
        self.send("protector icon (0x2154)", scorecard.protector_icon_slot(icon, index))

    def ev_request_achievements(self, msg):
        """0x211D RequestAllAchievementData -> 0x2120."""
        self.send_many([matchend.achievements_msg(self.account, self.data)])

    def ev_ack_achievement(self, msg):
        """0x211E AcknowledgeAchievementDisplayed (u32 DID): no more banner for it."""
        if len(msg.body) < 4 or self.account is None:
            return NotImplemented
        did = struct.unpack_from("<I", msg.body, 0)[0]
        st = self.account.d["achievements"].get(f"0x{did:08X}")
        if st:
            st["acknowledged"] = True
            self.save_account()
        self.log(f"achievement {did:#x} acknowledged (0x211e)")

    def ev_encounter_stats(self, msg):
        """0x2116 RequestAccountEncounterStats -> 0x2115 (one row per played encounter; statistics not mapped)."""
        rows = [(A.ACCOUNT_IID, 0, int(k, 16)) for k in sorted(self.account.d["stats"])] if self.account else []
        self.send(f"account encounter stats (0x2115): {len(rows)}", M.encounter_stats(rows))

    def ev_standings(self, msg):
        """0x2178 RequestAccountStandingsData -> 0x219E."""
        last = self.account.d["encounters"]["last"] if self.account else 0
        self.send("account standings (0x219e)", M.account_standings(matchend.ranked_values(
            self.account, last, self.ic.get("standings_layout", "reader")) if self.account else ()))

    def ev_static_standings(self, msg):
        """0x2193 RequestStaticStandingsData -> 0x219F."""
        self.send("static standings (0x219f)", M.static_standings())

    def ev_leaderboards(self, msg):
        """0x21A4 RequestLeaderboards (u32 encounter) -> 0x21A2 regional + 0x21A3 friends (only this account)."""
        enc = struct.unpack_from("<I", msg.body, 0)[0] if len(msg.body) >= 4 else 0
        acct = self.account
        r = acct.d["ranked"].get(f"0x{enc:08X}", {}) if acct else {}
        champ = self._default_pick()
        row = (A.ACCOUNT_IID, str(self.ic["player_name"]), r.get("rank", 0), r.get("sub", 0), 1, champ, 0)
        self.send_many([(f"leaderboard {enc:#x} (0x21a2)", M.leaderboard([row], 1, 0x21A2)),
                        (f"friends leaderboard {enc:#x} (0x21a3)", M.leaderboard([row], 1, 0x21A3))])

    def ev_champion_data_again(self, msg):
        """0x21A5: the champion list came empty -> 0x20ED again."""
        ev = [e for e in M.initial_events(self.roster(), 1, self.ic["player_name"]) if "(0x20ed)" in e[0]]
        self.send_many(ev)

    def ev_level_loaded(self, msg):
        """0xCC: the client's level is loaded (35 %, match-load-sequence.md): the objects may go out now."""
        if self.match is not None:
            self.match.level_loaded = True
            self.log("client: level loaded (0xcc)")
        return None

    def ev_silent(self, msg):
        """2026-10-25 (sweep-c2s.md): client telemetry and load / link steps that need no answer and no log line
        (0x20BE / 0x20B4 / 0x214F profiler statistics, 0x211B, 0x20D3, 0x207A, 0x00CC)."""
        return None

    def ev_remote_scriptlet(self, msg):
        """0x00DA (sweep-c2s.md, P): the client asks for a networked scriptlet on an object it does not own (it does
        not run it itself, 0x628bf0): u64 entity | one 0x8D entry. The server plays it on that entity by 0x8D
        ([ics] remote_scriptlets)."""
        if not self.ic.get("remote_scriptlets", True) or len(msg.body) < 10 or not self.match or not self.match.world:
            return None
        entity = struct.unpack_from("<Q", msg.body, 0)[0]
        body = b"\x00" + pack_compact(1) + msg.body[8:]
        self.send(f"remote scriptlet on {entity:#x} (0x8d, from 0xda)", M.build_message(entity, M.EVT_START_SCRIPTLETS, body))

    def ev_hold_position(self, msg):
        """0x20AB hold position (u8; sweep-c2s.md): 1 = the champion stops and drops its auto-attack."""
        m = self.match
        if not m or not m.world or not m.world.champion or not msg.body:
            return NotImplemented
        if msg.body[0]:
            ch = m.world.champion
            ch.attack_target = None
            ch.dest, ch.speed, ch.path = None, 0.0, []
            m.world.update(ch, f"{ch.name} holds position (0x20ab)")

    def ev_artifact_slots(self, msg):
        """0x212C artifact skill-slot mapping (list<u32>: slot = inventory index + 10; sweep-c2s.md): kept."""
        if len(msg.body) >= 4:
            n = struct.unpack_from("<I", msg.body, 0)[0]
            self.artifact_slots = list(struct.unpack_from(f"<{min(n, 16)}I", msg.body, 4)) if len(msg.body) >= 4 + 4 * min(n, 16) else []

    def ev_selected(self, msg):
        """0x20D1 the player's selected target changed (u64 old | u64 new; sweep-c2s.md): kept."""
        if len(msg.body) >= 16:
            self.selected_target = struct.unpack_from("<Q", msg.body, 8)[0]

    def ev_quiet(self, msg):
        """Client events that need no answer (machine info 0x20E3, login flags 0x20D4, rejoin attempt 0x20C4 with no
        room open, dodge-penalty request 0x21A8, UI metrics 0x218C, ready flags 0x2156 / 0x2108, telemetry)."""
        self.log(f"client event {msg.event_id:#x} ({len(msg.body)} bytes): no answer needed")

    # ---- chat ---------------------------------------------------------------------------------------------------
    def ev_say(self, msg):
        """0x20F6 say: StringInfo channel | wstr text -> echoed ([ics] chat_echo_event)."""
        p = chat.parse_say(msg.body)
        if p is None:
            return NotImplemented
        channel, text = p
        self.log(f"chat [{channel}] {text!r}")
        if self._chat_command(text, channel):
            return
        self.send_many(chat.echo(self.ic, str(self.ic["player_name"]), channel, text))

    def _chat_command(self, text, channel="All"):
        """Test commands typed in the chat ([ics] chat_commands): /anunciador N [canal] plays announcer event N
        (0x2039); /anunciador todos plays every known event, one every announcer_test_gap s, logging each."""
        if not self.ic.get("chat_commands", True):
            return False
        # 2026-10-26 00:16 (tester: /tour did nothing, the chat showed codes; only lines without "/" reached the server:
        # the client keeps "/" lines for its own commands): "!" works as well, and "tour ..." with no prefix
        text = text.strip()
        if text[:1] in ("/", "!"):
            words = text[1:].split()
        elif text.lower().split()[:1] in (["tour"], ["vitrina"], ["showroom"], ["vehiculo"]):
            words = text.split()
        else:
            return False
        if words and words[0].lower() in self.EMOTE_WORDS and self.ic.get("emote_chat_commands", True):
            # 2026-10-24 00:40 (tester: Alt+Numpad emotes did nothing; no 0x9F reached the server): /dance, /joke,
            # /laugh, /taunt, /oath (or bailar, broma, reir, provocar, juramento) in the match chat play the emote
            self.log(f"emote by chat: {words[0]}")
            return self._emote(self.EMOTE_WORDS[words[0].lower()]) or True
        if words and words[0].lower() in ("tour", "t", "vitrina", "showroom", "vehiculo") and self.ic.get("tour_command", True):
            # 2026-10-25 23:45 (tester: a tour over every element of the map to name what does not load): /tour (next),
            # /tour N, /tour atras, /tour auto S, /tour stop (ics/match/tour.py)
            m = self.match
            mode = getattr(m, "mode", None) if m else None
            if mode is None or not hasattr(mode, "world"):
                self.send_many(chat.echo(self.ic, "Tour", channel, "only in a match"))
                return True
            if getattr(mode, "tour", None) is None:
                from .match.tour import Tour
                mode.tour = Tour(mode, lambda text: self.send_many(chat.echo(self.ic, "Tour", channel, text)))
            if words[0].lower() in ("vitrina", "showroom"):
                mode.tour.showroom(words)
            elif words[0].lower() == "vehiculo":
                mode.tour.vehicle(words)
            else:
                mode.tour.command(words)
            return True
        if not words or words[0].lower() not in ("anunciador", "announcer"):
            return False
        from .match import announcer as A
        from .match.match import announcer_msgs
        m = self.match
        ch = m.world.champion if m and m.world else None
        src = ch.eid if ch else 0
        team = int(self.ic.get("team", 1))
        fallback = float(self.ic.get("announcer_test_fallback", 3.0) or 0)

        def play(ev):
            # the event by 0x2039 on its channel, then (fallback s later) its own-team line by 0x2001
            self.log(f"announcer test: event {ev} (0x2039 channel {A.channel(ev)}), "
                     f"line {A.line(ev)} by 0x2001 {fallback:g} s later")
            self.send_many(announcer_msgs(dict(self.ic, announcer_mode="2039"), ev, src, src, team))
            if fallback:
                self.later(fallback, lambda: self.send_many(
                    announcer_msgs(dict(self.ic, announcer_mode="2001"), ev, src, src, team)) if self.match is m else None)
        if len(words) > 1 and words[1].lower() in ("todos", "all"):
            gap = float(self.ic.get("announcer_test_gap", 7.0))
            for k, ev in enumerate(A.EVENTS):
                self.later(k * gap, lambda ev=ev: play(ev) if self.match is m else None)
        elif len(words) > 1 and words[1].isdigit():
            play(int(words[1]))
        return True

    def ev_tell(self, msg):
        """0x20CD tell: wstr target | wstr text -> echoed to the sender (nobody else is online)."""
        p = chat.parse_tell(msg.body)
        if p is None:
            return NotImplemented
        target, text = p
        self.log(f"chat tell to {target!r}: {text!r}")
        self.send_many(chat.echo(self.ic, f"[to {target}] {self.ic['player_name']}", "Tell", text))

    def ev_admin(self, msg):
        """0x2148 / 0x2160 admin console commands (gated by the client's admin check): logged only."""
        self.log(f"admin command {msg.event_id:#x}: {msg.body.hex()}")

    # ---- events with two names (full-protocol.md / full-account-social.md): decided by context ------------------
    def _in_custom(self):
        return self.custom is not None and self.phase in (MENU, CONNECTED)

    def ev_0x202d(self, msg):
        """0x202D: LobbyUIReady {QueueKey} in a lobby (full-protocol.md) / Create_CustomMatch {QueueKey}
        (full-account-social.md) from the menu."""
        if len(msg.body) < 8:
            return NotImplemented
        did, flags = struct.unpack_from("<II", msg.body, 0)
        if self.phase in (GAME_CONNECTED, LOBBY) and self.match:
            self.log("0x202d = LobbyUIReady (lobby open): lobby state again")
            if self.match.lobby:
                self.send_many(self.match.lobby.state_msgs())
            return
        self.log(f"0x202d = Create_CustomMatch {did:#x} (from the menu)")
        # the installed encounters (cached; Data.encounter would wait for a pack read of another thread)
        if did not in dict(self.data.encounter_list()):
            self.send("custom match creation failed (0x2042)", M.cm_creation_failed(""))
            return
        self.custom = CustomMatch(self, did, flags)
        self.send_many(self.custom.created_msgs())

    def ev_0x2057(self, msg):
        """0x2057: RequestMyAmplifierSet (lobby) / Launch_CustomMatch (custom match room)."""
        if self._in_custom():
            self.log("0x2057 = Launch_CustomMatch")
            cm = self.custom
            self.send("custom match launched (0x2040)", M.cm_launched())
            self.custom = None
            self.start_queue(cm.encounter, cm.qflags, custom=True)
            if self.match:
                self._referral()
            return
        lob = self._lobby_or_none()
        if lob is None:
            return NotImplemented
        self.log("0x2057 = RequestMyAmplifierSet")
        self.send("my amplifier set (0x204a)", M.picked_amplifier_set(lob.room, lob.amp_bytes(lob.me.amp)))

    def ev_0x2064(self, msg):
        """0x2064: RequestMyStolenPowers (lobby) / Leave_CustomMatch (custom match room)."""
        if self._in_custom():
            self.log("0x2064 = Leave_CustomMatch")
            self.custom = None
            self.send("custom match: left (0x205d)", M.cm_participant_removed(A.ACCOUNT_IID))
            return
        lob = self._lobby_or_none()
        if lob is None:
            return NotImplemented
        self.log("0x2064 = RequestMyStolenPowers")
        self.send("my Stolen Powers (0x2004)", M.picked_stolen_powers(lob.room, *lob.me.stolen))

    def ev_0x205a(self, msg):
        """0x205A: Draft_TradeResponse (lobby) / Cancel_CustomMatch."""
        if self._in_custom():
            self.log("0x205a = Cancel_CustomMatch")
            self.custom = None
            self.send("custom match cancelled (0x2011)", M.cm_cancelled())
            return
        self.log("0x205a = Draft_TradeResponse (bots answer trades themselves)")

    def ev_0x2026(self, msg):
        """0x2026 (u64, u32): Draft_RequestTrade (lobby) / AssignTeam_CustomMatch."""
        if self._in_custom() and len(msg.body) >= 12:
            target, team = struct.unpack_from("<QI", msg.body, 0)
            self.log(f"0x2026 = AssignTeam_CustomMatch {target:#x} -> team {team}")
            if target == A.ACCOUNT_IID:
                self.custom.team = team
            self.send("custom match team (0x2076)", M.cm_assigned_team(target, team))
            return
        return self.ev_trade(msg)

    def ev_0x200a(self, msg):
        """0x200A (u64): ExitLobbyToMainMenu (lobby) / ChangeCoordinator_CustomMatch."""
        if self._in_custom() and len(msg.body) >= 8:
            new = struct.unpack_from("<Q", msg.body, 0)[0]
            self.log(f"0x200a = ChangeCoordinator_CustomMatch -> {new:#x}")
            self.send("custom match coordinator (0x2036)", M.cm_coordinator(A.ACCOUNT_IID, new))
            return
        return self.ev_exit_lobby(msg)

    def ev_0x200d(self, msg):
        """0x200D (u8): RequestChangeAmplifierSet slot (lobby) / InviteResponse_CustomMatch."""
        if self._lobby_or_none() is not None and msg.body:
            return self.ev_change_amplifier_set(msg)
        self.log(f"0x200d = InviteResponse_CustomMatch ({msg.body.hex()}): no invitation is pending")

    def ev_0x206a(self, msg):
        """0x206A (u64, u32, u8): PlayerSelectedEarlyLaunch (lobby) / GivePerm_CustomMatch."""
        if self._in_custom() and len(msg.body) >= 13:
            target, perm, grant = struct.unpack_from("<QIB", msg.body, 0)
            self.log(f"0x206a = GivePerm_CustomMatch {target:#x} perm {perm} {grant}")
            self.send("custom match permission (0x2035)", M.cm_permission(target, perm, grant))
            return
        return self.ev_early_launch(msg)

    def ev_0x2108(self, msg):
        """0x2108 (u32): TeamDisplayReady (lobby) / SetEncounter (custom match)."""
        if self._in_custom() and len(msg.body) >= 4:
            did = struct.unpack_from("<I", msg.body, 0)[0]
            self.log(f"0x2108 = SetEncounter_CustomMatch {did:#x}")
            self.custom.encounter = did
            self.send("custom match encounter (0x2109)", M.cm_set_encounter(did))
            return
        return self.ev_quiet(msg)

    def ev_0x214e(self, msg):
        """0x214E (u32, StringInfo, StringInfo): TriggerWaitAfterReadyFlag / SetTeamNames (custom match)."""
        if self._in_custom() and len(msg.body) >= 4:
            team = struct.unpack_from("<I", msg.body, 0)[0]
            try:
                long_name, pos = chat._string_info(msg.body, 4)
                short_name, pos = chat._string_info(msg.body, pos)
            except (IndexError, ValueError, struct.error):
                long_name = short_name = ""
            self.log(f"0x214e = SetTeamNames team {team}: {long_name!r} / {short_name!r}")
            self.custom.team_names[team] = (long_name, short_name)
            self.send("custom match team name (0x2151)", M.cm_team_name(team, long_name, short_name))
            return
        return self.ev_quiet(msg)

    def ev_0x20fd(self, msg):
        """0x20FD: RequestTeamNames (lobby) / Randomize (custom match): the one human goes to a random team."""
        if self._in_custom():
            import random
            self.custom.team = random.choice((1, 2))
            self.log(f"0x20fd = Randomize: team {self.custom.team}")
            self.send("custom match team (0x2076)", M.cm_assigned_team(A.ACCOUNT_IID, self.custom.team))
            return
        return self.ev_quiet(msg)

    def ev_0x2017(self, msg):
        """0x2017 (u64, u32): RequestStolenPowerList (lobby) / MovePosition_CustomMatch."""
        if self._in_custom() and len(msg.body) >= 12:
            target, direction = struct.unpack_from("<QI", msg.body, 0)
            self.custom.position = max(0, self.custom.position + (1 if direction else -1))
            self.log(f"0x2017 = MovePosition_CustomMatch {target:#x} -> {self.custom.position}")
            self.send("custom match moved (0x2048)", M.cm_moved(target, self.custom.position))
            return
        lob = self._lobby_or_none()
        if lob is None:
            return NotImplemented
        self.log("0x2017 = RequestStolenPowerList")
        self.send("my Stolen Powers (0x2004)", M.picked_stolen_powers(lob.room, *lob.me.stolen))

    def ev_0x2025(self, msg):
        """0x2025 (u64): RequestCharacterPickerInformation (lobby) / Kick_CustomMatch."""
        if self._in_custom():
            self.log("0x2025 = Kick_CustomMatch (nobody else is in the room)")
            return
        lob = self._lobby_or_none()
        if lob is None:
            return NotImplemented
        self.log("0x2025 = RequestCharacterPickerInformation: lobby slots again")
        self.send_many([lob.slot_msg(s) for s in lob.slots])

    def ev_0x201e(self, msg):
        """0x201E (wstr): RequestAllPregameTips (lobby; tips are built by the client) / Invite_CustomMatch."""
        self.log(f"0x201e = {'Invite_CustomMatch (no other player online)' if self._in_custom() else 'RequestAllPregameTips'}")

    def ev_0x2066(self, msg):
        """0x2066 (u64): RequestCustomMatchData (custom match) / UI_RemoveContact."""
        if self._in_custom():
            self.log("0x2066 = RequestCustomMatchData")
            self.send_many(self.custom.created_msgs())
            return
        self.log("0x2066 = UI_RemoveContact (no contacts are kept yet)")

    def ev_contacts(self, msg):
        """Contacts requests (full-account-social.md 1.1; several carry custom-match names in full-protocol.md):
        0x20C1 note, 0x2094 status message, 0x20E6 create group, 0x20FB destroy group, 0x219A / 0x2199 (un)ignore,
        0x20A1 friend request, 0x20C6 invite response, 0x219B Steam invites, 0x20F4 move to group, 0x200B
        presence. Kept on the account; only "group created" (0x2014) has an answer with a known layout."""
        acct = self.account
        ev, b = msg.event_id, msg.body
        social = acct.d["social"] if acct else {}
        try:
            if ev == 0x20E6:
                n, pos = read_compact(b, 0)
                name = b[pos:pos + 2 * n].decode("utf-16-le")
                gid = social.get("next_group", 1)
                social["next_group"] = gid + 1
                social.setdefault("groups", []).append({"id": gid, "name": name})
                self.send(f"contact group {name!r} created (0x2014)", M.contact_group_created(gid, name))
            elif ev == 0x2094:
                n, pos = read_compact(b, 0)
                acct.d["profile"]["status"] = b[pos:pos + 2 * n].decode("utf-16-le")
            elif ev in (0x219A, 0x2199):
                n, pos = read_compact(b, 0)
                name = b[pos:pos + 2 * n].decode("utf-16-le")
                ign = [x for x in social.get("ignored", []) if x != name]
                social["ignored"] = ign + ([name] if ev == 0x219A else [])
            self.log(f"contacts event {ev:#x} ({len(b)} bytes) kept")
        except (IndexError, UnicodeDecodeError, struct.error, KeyError, TypeError):
            return NotImplemented
        self.save_account()


HANDLERS = {
    0x20EB: Session.ev_join_queue,
    0x20C3: Session.ev_leave_queue,
    0x20CA: Session.ev_accept_match,
    0x20F2: Session.ev_connect_to_lobby,
    0x20D5: Session.ev_loading_percent,
    0x2: Session.ev_notice,
    0x20EE: Session.ev_order,
    0x9F: Session.ev_script_rpc,
    0x216E: Session.ev_preference,
    0x2136: Session.ev_ping,
    0x20EA: Session.ev_skill_events,
    0x2140: Session.ev_conversation_done,
    0x20A6: Session.ev_end_page_closed,
    0x212E: Session.ev_ask_achievement_banners,
    0x2124: Session.ev_ask_pending_rewards,
    0x2128: Session.ev_claim_reward,
    0x20E4: Session.ev_select_character,
    0x2102: Session.ev_select_or_draft,
    0x208E: Session.ev_lock,
    0x2089: Session.ev_early_launch,
    0x207D: Session.ev_change_stolen_power,
    0x2098: Session.ev_change_amplifier_set,
    0x200D: Session.ev_0x200d,
    0x20D6: Session.ev_trade,
    0x20F1: lambda s, m: s.log(f"draft trade response {m.body.hex()} (0x20f1): bots answer trades themselves"),
    0x20BF: Session.ev_exit_lobby,
    0x208B: Session.ev_purchase,
    0x20A7: Session.ev_sell,
    0x12D: Session.ev_left_world,
    # account screens
    0x20BA: Session.ev_request_amplifier_sets,
    0x2106: Session.ev_request_boutique,
    0x20FC: Session.ev_save_amplifier_set,
    0x210E: Session.ev_store_purchase,
    0x2110: Session.ev_store_confirm,
    0x2111: Session.ev_store_cancel,
    0x95: Session.ev_web_ticket,
    0x2093: Session.ev_set_protector_icon,
    0x211D: Session.ev_request_achievements,
    0x211E: Session.ev_ack_achievement,
    0x2116: Session.ev_encounter_stats,
    0x2178: Session.ev_standings,
    0x2193: Session.ev_static_standings,
    0x21A4: Session.ev_leaderboards,
    0x21A5: Session.ev_champion_data_again,
    0x20BE: Session.ev_silent, 0x20B4: Session.ev_silent, 0x214F: Session.ev_silent, 0x211B: Session.ev_silent,
    0x20D3: Session.ev_silent, 0x207A: Session.ev_silent, 0xCC: Session.ev_level_loaded,
    0xDA: Session.ev_remote_scriptlet, 0x20AB: Session.ev_hold_position, 0x212C: Session.ev_artifact_slots,
    0x20D1: Session.ev_selected,
    0x20E3: Session.ev_quiet, 0x20D4: Session.ev_quiet, 0x20C4: Session.ev_quiet, 0x21A8: Session.ev_quiet,
    0x218C: Session.ev_quiet, 0x2156: Session.ev_quiet,
    # chat
    0x20F6: Session.ev_say,
    0x20CD: Session.ev_tell,
    0x2148: Session.ev_admin, 0x2160: Session.ev_admin,
    # two names: decided by context
    0x202D: Session.ev_0x202d, 0x2057: Session.ev_0x2057, 0x2064: Session.ev_0x2064, 0x205A: Session.ev_0x205a,
    0x2026: Session.ev_0x2026, 0x200A: Session.ev_0x200a, 0x206A: Session.ev_0x206a, 0x2108: Session.ev_0x2108,
    0x214E: Session.ev_0x214e, 0x20FD: Session.ev_0x20fd, 0x2017: Session.ev_0x2017, 0x2025: Session.ev_0x2025,
    0x201E: Session.ev_0x201e, 0x2066: Session.ev_0x2066,
    # contacts
    0x20C1: Session.ev_contacts, 0x2094: Session.ev_contacts, 0x20E6: Session.ev_contacts, 0x20FB: Session.ev_contacts,
    0x219A: Session.ev_contacts, 0x2199: Session.ev_contacts, 0x20A1: Session.ev_contacts, 0x20C6: Session.ev_contacts,
    0x219B: Session.ev_contacts, 0x20F4: Session.ev_contacts, 0x200B: Session.ev_contacts,
}
