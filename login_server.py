"""Local stand-in for Turbine's WebLoginApp SOAP login server (ls.infinitecrisis.com).

Run this, then start the game. Every request is logged in full to the console
and logs/requests.log so unknown calls can be identified and implemented.

Implemented:
  LauncherWS  getLauncherData  -> launcher configuration (name/value pairs)
  AuthenticateWS  AuthSelect   -> GUESSED login response (field names come from
                                  the client's gSOAP schema; layout unverified)

Also listens on USER_SERVER_PORT and hex-dumps whatever the client sends to
the "user server" it is told to connect to after login (stage 3 protocol).
"""
import datetime
import math
import http.server
import os
import re
import socket
import struct
import threading
import time
from xml.sax.saxutils import escape

from Crypto.Cipher import PKCS1_OAEP, PKCS1_v1_5
from Crypto.PublicKey import RSA

HOST, PORT = "127.0.0.1", 8888
USER_SERVER_PORT = 9000
# Game ("world") server the client is referred to when a match starts (packet
# 0x800 Referral). A ConnectRequest received on that NEW connection takes the
# other branch of the handler (rva 0xbe4950 -> 0xbe4b31 -> 0xbe4550) and posts
# connection notice 4 -> gmConnectionManager +0x70 bit 1 (rva 0x69aaa0), one
# of the three flags match loading (0x699e20) waits for.
GAME_SERVER_PORT = 9001
SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(SERVER_DIR, "logs", "requests.log")
# Private half of the key patched into InfiniteCrisis_patched.exe (file offset 0x11a1f58).
with open(os.path.join(SERVER_DIR, "keys", "server_private.pem"), "rb") as _f:
    SERVER_KEY = RSA.import_key(_f.read())

# Config the real server used to push to the launcher. Keys match those the
# launcher reads via Config::GetValue (see TurbineLauncher.log for misses).
LAUNCHER_DATA = {
    "Launcher.SupportedLocaleList": "en",
    "Patch.Disable": "true",
    "Patch.Regions": "NA|http://127.0.0.1",
    # The launcher runs ClientLauncher.Filename (Turbine's crash-reporting
    # wrapper) with ArgTemplate. The wrapper uses "/" flags; everything after
    # "//" is passed through to InfiniteCrisis.exe.
    "GameClient.Filename": "InfiniteCrisis.exe",
    "ClientLauncher.Filename": "turbineclientlauncher.exe",
    "GameClient.ArgTemplate": (
        "/e {CLIENTEXE} /n {LANGUAGE} // "
        "--loginurl {LOGINURL} --loginregion {REGION} "
        "--reportingurl {REPORTINGURL} --language {LANGUAGE}"
    ),
    "URL.Help": "http://127.0.0.1",
    "URL.Register": "http://127.0.0.1",
}

SOAP_ENVELOPE = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<S:Envelope xmlns:S="http://schemas.xmlsoap.org/soap/envelope/">'
    "<S:Body>{body}</S:Body></S:Envelope>"
)


def get_launcher_data_response():
    pairs = "".join(
        f"<nameValuePairs><name>{escape(k)}</name><value>{escape(v)}</value></nameValuePairs>"
        for k, v in LAUNCHER_DATA.items()
    )
    return (
        '<ns2:getLauncherDataResponse xmlns:ns2="http://webloginapp.wbnet.turbine.com/">'
        f"<return>{pairs}</return></ns2:getLauncherDataResponse>"
    )


def auth_select_response():
    # Field order and types follow the client's gSOAP authResponseMessage
    # deserializer (InfiniteCrisis.exe rva 0x6de5e1..0x6de7b9).
    # errorString must be ABSENT on success: the login handler (rva 0x69b952)
    # treats any non-null errorString other than "NO_DISPLAY_NAME" as a silent
    # failure, so even an empty <errorString/> hangs on "Logging in".
    fields = {
        "errorString": None,
        "loginTicket": "1001",  # xsd:long
        "newSocialMediaEncryptionKey": None,
        "oldSocialMediaEncryptionKey": None,
        "randomID": "1",
        "sessionKey": "LOCALSESSIONKEY0001",
        "userServerAddr": HOST,
        "userServerPort": str(USER_SERVER_PORT),  # xsd:int
    }
    inner = "".join(
        f"<{k}>{escape(v)}</{k}>" for k, v in fields.items() if v is not None
    )
    return (
        '<ns2:AuthSelectResponse xmlns:ns2="http://webloginapp.wbnet.turbine.com/">'
        f"<return>{inner}</return></ns2:AuthSelectResponse>"
    )


# SOAP operation name (first element inside Body) -> response body builder
OPERATIONS = {
    "getLauncherData": get_launcher_data_response,
    "AuthSelect": auth_select_response,
}


class LoginHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _log(self, body, note):
        entry = (
            f"\n===== {datetime.datetime.now().isoformat()} {self.command} {self.path} [{note}]\n"
            f"{self.headers}"
            f"{body.decode('utf-8', errors='replace')}\n"
        )
        print(entry, flush=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(entry)

    def _handle(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""

        match = re.search(rb"<(?:[\w.-]+:)?Body[^>]*>\s*<(?:[\w.-]+:)?(\w+)", body)
        operation = match.group(1).decode() if match else None
        builder = OPERATIONS.get(operation)
        self._log(body, f"op={operation} {'handled' if builder else 'UNHANDLED'}")

        payload = SOAP_ENVELOPE.format(body=builder() if builder else "").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/xml; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = do_POST = do_HEAD = _handle

    def log_message(self, fmt, *args):
        pass


def log_line(text):
    print(text, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(text + "\n")


def hexdump(data):
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        hexpart = " ".join(f"{b:02x}" for b in chunk)
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{i:08x}  {hexpart:<48}  {text}")
    return "\n".join(lines)


def try_decrypt_session_key(data):
    """Find the RSA-encrypted session key in the client hello and try to
    decrypt it with our private key (requires InfiniteCrisis_patched.exe,
    whose embedded public key was replaced with ours)."""
    marker = data.find(b"\x043des")
    if marker < 0 or len(data) < marker + 9:
        return
    blob_len = struct.unpack_from("<I", data, marker + 5)[0]
    blob = data[marker + 9:marker + 9 + blob_len]
    if blob_len != 128 or len(blob) != 128:
        log_line(f"    hello: unexpected key blob length {blob_len}")
        return
    attempts = {
        "OAEP-SHA1": lambda: PKCS1_OAEP.new(SERVER_KEY).decrypt(blob),
        "PKCS1-v1.5": lambda: PKCS1_v1_5.new(SERVER_KEY).decrypt(blob, None),
    }
    for name, attempt in attempts.items():
        try:
            plain = attempt()
        except ValueError:
            plain = None
        if plain:
            log_line(f"    hello: session key decrypted with {name}: {len(plain)} bytes {plain.hex()}")
            return plain
    log_line("    hello: could not decrypt session key (is the client InfiniteCrisis_patched.exe?)")


def user_server_client(conn, addr):
    log_line(f"\n===== {datetime.datetime.now().isoformat()} USER SERVER connect from {addr}")
    first = True
    pending = b""
    QUEUE_STATE.clear()
    QUEUE_STATE["user_conn"] = conn
    with conn:
        while True:
            data = conn.recv(65536)
            if not data:
                break
            log_line(f"--- {datetime.datetime.now().isoformat()} recv {len(data)} bytes\n{hexdump(data)}")
            if not first:
                pending += data
                pending = handle_client_frames(conn, pending)
            if first:
                try_decrypt_session_key(data)
                first = False
                reply = build_hello_reply(data)
                if reply:
                    conn.sendall(reply)
                    log_line(f"--- sent {len(reply)} bytes (welcome)\n{hexdump(reply)}")
                for label, msg in build_initial_events():
                    conn.sendall(msg)
                    log_line(f"--- sent {len(msg)} bytes ({label})\n{hexdump(msg)}")
    log_line(f"===== USER SERVER disconnect {addr}")


def read_compact(buf, pos):
    """Inverse of pack_compact; returns (value, new_pos)."""
    b0 = buf[pos]
    if b0 < 0x80:
        return b0, pos + 1
    if b0 < 0xC0:
        return ((b0 & 0x3F) << 8) | buf[pos + 1], pos + 2
    if b0 < 0xE0:
        return (((b0 & 0x1F) << 24) | (buf[pos + 1] << 16)
                | struct.unpack_from("<H", buf, pos + 2)[0]), pos + 4
    return struct.unpack_from("<I", buf, pos + 1)[0], pos + 5


def handle_client_frames(conn, buf):
    """Split the stream into frames (u32 len | payload) and answer the game
    messages we understand. Game message payload (as sent by the client):
      u8 0x02 | u64 dest service | u8 flags | compact event id | body
    Returns the unconsumed tail."""
    while len(buf) >= 4:
        n = struct.unpack_from("<I", buf, 0)[0]
        if len(buf) < 4 + n:
            break
        payload, buf = buf[4:4 + n], buf[4 + n:]
        if len(payload) < 11 or payload[0] != 0x02:
            continue
        dest = struct.unpack_from("<Q", payload, 1)[0]
        event_id, pos = read_compact(payload, 10)
        body = payload[pos:]
        log_line(f"    client event {event_id:#x} dest {dest:#018x} flags {payload[9]:#x} body {body.hex()}")
        for label, msg in client_event_replies(dest, event_id, body):
            # Replies always go out on the login connection (also for events
            # that arrived on the game connection).
            with USER_SEND_LOCK:
                (QUEUE_STATE.get("user_conn") or conn).sendall(msg)
            log_line(f"--- sent {len(msg)} bytes ({label})\n{hexdump(msg)}")
    return buf


def client_event_replies(dest, event_id, body):
    """Replies to client requests: list of (label, message)."""
    if event_id == 0x20EB and QUEUE_STATE.get("referred") and time.time() - QUEUE_STATE.get("referred_at", 0) < 90:
        # A second Launch press while the match is being set up: answering it
        # sent a second referral, which tore down the game connection and then
        # the login connection ("ID_ConnectionError_ConnectionReset").
        return []
    if event_id == 0x20EB and len(body) >= 8:
        # JoinQueue (script GM_UI.SendNotice_JoinQueue(didMatch, bSolo, bDraft,
        # bRanked); serializer rva 0x440120): u32 encounter did | u32 queue flags
        # | u8 solo | u32 (-1). Reply 0x20C0 = joined queue (serializer rva
        # 0x43fe00, handler 0x637c70 -> GM_UI.RecvNotice_JoinedQueue):
        #   u8 base | u32 did | u32 flags | f32 | f32 (wait estimates) | u32 status
        # (status 0x10000049 is special-cased by the handler).
        did, qflags = struct.unpack_from("<II", body, 0)
        QUEUE_STATE["encounter"] = (did, qflags)
        reply =b"\x00" + struct.pack("<IIffI", did, qflags, 0.0, 0.0, 0)
        # Then 0x20FA = match found (serializer rva 0x28f240: u8 base | u32 | u32;
        # handler 0x615550 -> GM_UI.RecvNotice_FoundMatch(nMaxPlayers, nTimeout)
        # -> WrapperMain EVENT_FOUND_MATCH). EXPERIMENT: 1 player, 30 s.
        found = b"\x00" + struct.pack("<II", 1, 30)
        return [(f"joined queue (0x20c0) for {did:#x}", build_message(SVC_PLAYER_SYSTEM, 0x20C0, reply)),
                ("found match (0x20fa)", build_message(SVC_PLAYER_SYSTEM, 0x20FA, found))]
    if event_id == 0x20CA and "encounter" in QUEUE_STATE:
        # AcceptMatch (empty body; script SendNotice_AcceptMatch, sent
        # automatically for a 1-player match). Reply 0x2028 = lobby room created
        # (serializer rva 0x446620, handler 0x6bc3c0 -> GM_Lobby.RecvNotice_
        # LobbyRoomCreated or UI state event 0x14):
        #   u8 base | u32 encounter did | u32 queue flags | u32 count + StringInfo[]
        #   | u32 count + StringInfo[]   (team names, rva 0x441b20 / 0x1a9580)
        did, qflags = QUEUE_STATE["encounter"]
        room = b"\x00" + struct.pack("<IIII", did, qflags, 0, 0)
        QUEUE_STATE["referred"] = True
        QUEUE_STATE["referred_at"] = time.time()
        # 0x20AD = number of players who accepted (serializer rva 0x439500: u8 base
        # | u32 n; handler 0x60dbe0 -> GM_UI.RecvNotice_NumPlayersAcceptedMatch).
        # Script MatchFoundRibbon calls GoToLobby() once n == nMaxPlayers and the
        # lobby room exists (RecvNotice_LobbyRoomCreated) -> lobby screen.
        accepted = b"\x00" + struct.pack("<I", 1)
        return [("players accepted (0x20ad)", build_message(SVC_PLAYER_SYSTEM, 0x20AD, accepted)),
                ("lobby room created (0x2028)", build_message(SVC_PLAYER_SYSTEM, 0x2028, room)),
                (f"referral -> game server 127.0.0.1:{GAME_SERVER_PORT}", build_referral("127.0.0.1", GAME_SERVER_PORT))]
    if event_id == 0x20D5 and len(body) >= 4:
        # Client reports its own world-load percent (u32 percent, no base byte;
        # seen 10, 15, 25). The server echoes every player's percent as 0x2031
        # (serializer rva 0x4459e0, handler 0x6b8730 -> 0x4eed40 ->
        # GM_Lobby.RecvNotice_UpdateLobbyLoadingPercent(teamNumbers,
        # teamIndexes, percents) -> loading screen bar): u8 base | u32 n + u32[]
        # team numbers | u32 n + u32[] team indexes | u32 n + u32[] percents |
        # u32 room id (must equal lobby+0x4bc). Our slot is team 0 index 0
        # (the first two u32s of 0x2029).
        percent = struct.unpack_from("<I", body, 0)[0]   # client events: no base byte
        pct = (b"\x00" + struct.pack("<II", 1, TEAM_NUMBER) + struct.pack("<II", 1, 0)
               + struct.pack("<II", 1, percent) + struct.pack("<I", ROOM_ID))
        return [(f"lobby loading percent {percent} (0x2031)", build_message(SVC_PLAYER_SYSTEM, 0x2031, pct))]
    if event_id == 0x20EE:
        mover_order(body)
        return []
    if event_id == 0x2136 and len(body) >= 20:
        return answer_ping(body)
    if event_id == 0x2 and len(body) >= 12 and body[:4] == bytes.fromhex("17010010"):
        # The client reports a cinematic state change to the player object:
        # u32 0x10000117 | u32 state (4 = finished) | u32 cinematic DID.
        state, did = struct.unpack_from("<II", body, 4)
        if state == 4 and did == CINEMATIC_DID:
            return tutorial_start()
    if event_id == 0x2 and body[:4] == bytes.fromhex("5e010010"):
        # Notice 0x1000015e to the player object: arrives with ServerLoadComplete
        # (about 5 s before the HUD curtain goes up).
        QUEUE_STATE["in_world"] = True
        log_line("    client reports load complete (notice 0x1000015e)")
        # The intro cinematic must start IN the world (the HUD curtain goes up
        # ~5 s after this notice): started during the loading screen it plays
        # half hidden and its Superman conversations are never queued.
        if CINEMATIC_DID and not QUEUE_STATE.get("cinematic_sent"):
            QUEUE_STATE["cinematic_sent"] = True
            def start_cinematic():
                send_user(build_message(LOCAL_PLAYER_ID, 0x20F5, bytes(1) + struct.pack("<II", 0x1, CINEMATIC_DID)))
                log_line(f"--- sent camera/cinematic 0x20f5 did {CINEMATIC_DID:#x}")
            threading.Timer(CINEMATIC_DELAY, start_cinematic).start()
        return []
    if event_id == 0x20F2:
        TUTORIAL["step"] = 0
        QUEUE_STATE["in_world"] = False
        QUEUE_STATE["cinematic_sent"] = False
        # The match objects are created a little later (create_match_objects):
        # the client loads the encounter's conversation table (0x40000cb7, pack
        # 0xa0000256) from a listener that fires when the PLAYER OBJECT appears
        # (rva 0x635dc0 <- notice 0x11). If the object arrives before that pack
        # is loaded the table stays "not loaded" for the whole match and no
        # conversation can start (seen as an on/off race, 2026-10-05).
        QUEUE_STATE["avatar_seq"] = 0
        def create_match_objects():
            send_user(build_match_objects(link_agent=False))
            log_line("--- sent create champion agent + player (delayed)")
            QUEUE_STATE["avatar_seq"] = 1   # game-server loop then streams position updates
        threading.Timer(MATCH_OBJECTS_DELAY, create_match_objects).start()
        # ConnectToLobbyMessage (sent once the lobby UI is ready, rva 0x6bea40 ->
        # 0x698850). Answer with our player's lobby slot (0x2029) and then end
        # the room (0x2016) so CheckTransitionToWorldLoad (0x6b8ec0) finds a
        # selected champion and fires UI state 0x23 (TransitionToWorldLoad).
        # EXPERIMENT: then create the local player object as the champion's avatar.
        # Each champion's heavy pack holds exactly one world state (0x2E) whose
        # parent is the champion entity (0x2D); Gaslight Batman: 0x2E0001B2 ->
        # 0x2D000115 (pack 0xa0000076). The match-load pending mask (flow+0x68)
        # waits for the local player object (bit 2: rva 0x699140 / 0x2351d0;
        # bit 8: 0x696a00). Sent after 0x2016, i.e. after the world cleanup
        # (0x342120) that crashed on the old login-time placeholder object.
        # A non-zero room id is needed by the loading-progress routine 0x6964b0
        # (lobby+0x4bc) before it can fire ServerLoadComplete (UI 0x33): 0x2029
        # carries it (accepted while lobby+0x4bc is still 0), 0x204C stores it,
        # 0x2016 / 0x206D must then use the same id.
        room = struct.pack("<I", ROOM_ID)
        return [("lobby player slot (0x2029)", build_message(SVC_PLAYER_SYSTEM, 0x2029, build_lobby_player())),
                ("lobby state (0x204c)", build_message(SVC_PLAYER_SYSTEM, 0x204C, build_lobby_state())),
                ("end room check (0x2016)", build_message(SVC_PLAYER_SYSTEM, 0x2016, b"\x00" + room)),
                # 0x206D (u8 base | u32 room id; handler 0x6b84f0) sets lobby+0x1c0,
                # another ServerLoadComplete condition.
                ("all loaded? (0x206d)", build_message(SVC_PLAYER_SYSTEM, 0x206D, b"\x00" + room)),
                # EXPERIMENT 2026-10-05: 0x2053 "Start" (serializer 0x4465b0: u8 base |
                # u32 (-> charsys+0x6c) | list | list, both u32 count; handler 0x6ba390)
                # sets the lobby manager's "started" byte ([0x1777138]+0xac, getter
                # 0x6bee50). Only with that byte set does the loading-progress routine
                # (0x6964b0 -> 0x696567..) take its "match started" branch at
                # ServerLoadComplete, which sets bit 4 of the dialog manager's gate
                # (+0x14c, 0x613b10). Without it the conversation queue never ticks,
                # so the intro cinematic's Superman lines stay queued (verified by
                # poking the bit live). 0x2028 and 0x20AF reset the byte (0x6bc2c0),
                # so this must come after them. Side effect: fires UI state 0x14.
                *([] if not SEND_MATCH_START else [("match start (0x2053)", build_message(SVC_PLAYER_SYSTEM, 0x2053,
                                                       b"\x00" + struct.pack("<III", 0, 0, 0)))]),
                # (The first object creation, WITHOUT the agent link, follows from
                # the timer above; the link is added by the game-server loop's
                # resends, so the client sees the property change.)
                ]
    return []


SEND_CHARACTER_ENTRY = True
# Lobby team of our player: script utils.TeamUtils.TEAM_A = 1 (TEAM_B = 2); the
# loading screen (class Curtain) only has displays for teams 1 and 2.
TEAM_NUMBER = 1


def build_character_set():
    """Event 0xCE (account character set; serializer rva 0x45310): u8 base |
    u32 count | entries (reader rva 0x216f0: u64 id | u64 | wstring name |
    u32 | property table | property table) | property table.
    EXPERIMENT: one entry. With an entry the client acts on the first one
    (rva 0x48a860) and sends 0x20D4 to the server -- apparently starting a
    CHARACTER SESSION, which the match needs (the in-match disconnect reason
    was ID_ConnectionError_EndCharacterSession and the world-ready flags
    flow+0x78 / charsys+0x100 were never set)."""
    if not SEND_CHARACTER_ENTRY:
        return b"\x00" + struct.pack("<I", 0) + b"\x00" + pack_compact(0)
    empty_table = b"\x00" + pack_compact(0)
    name = "Player"
    entry = (struct.pack("<QQ", LOCAL_PLAYER_ID, 0)
             + pack_compact(len(name)) + name.encode("utf-16le")
             + struct.pack("<I", 0) + empty_table + empty_table)
    return b"\x00" + struct.pack("<I", 1) + entry + empty_table


def string_info(text):
    """StringInfo (rva 0x1a9580), literal form: u8 mode 1 | compact length +
    UTF-16 | variables table (u8 size class | compact count)."""
    return b"\x01" + pack_compact(len(text)) + text.encode("utf-16le") + b"\x00" + pack_compact(0)


def build_lobby_player(champion=None, name="Player"):
    """EXPERIMENT: event 0x2029 = one lobby player slot (serializer rva 0x4479b0,
    execute 0x4b9150, handler 0x6bd0a0 -> slot filler 0x6bbb90). Layout:
      u8 base
      S (rva 0x445670, OPTIONAL: u8 present flag, rest only if 1): u8 | u32 | u32 | u32 | u32 n + u32[] | u32 n + u64[] (write 0x2ac5c0 / read 0x1bce30) | u32 | u32 | u64
      u32 (slot +0xb8) | u32 (+0xc8) | u64 PLAYER ID (+0xd8; matched against the
      local id from rva 0x14b0 = global 0x17579f0, which is 0 for us) |
      StringInfo name (+0xe8) | u8 (+0xf8) | u32 CHAMPION variant DID (+0x118; for
      the local player -> character system selects it) | u32 (+0x128) | u8
      (+0x188) | u32 ROOM ID (must equal lobby+0x4bc, 0 without a 0x204C) |
      u32 sequence (must not go backwards) | 7 x u32 (room +4..+0x14, +0x1bc,
      +0x1c0 / slot +0x158, +0x168)
      struct (rva 0x46fb20): u32 | u64 | u32 | StringInfo | wstring (compact
      length + UTF-16, rva 0x215d0) | u32 | compact n + u32[] (rva 0x13d570)"""
    champion = champion or TUTORIAL_CHAMPION
    # S is OPTIONAL: its first byte is a presence flag, and with 0 nothing else
    # of S is read (verified with the stream cursor: 1 byte consumed). Sending
    # the 36 field bytes anyway shifted every later field (champion read as 0).
    s = b"\x00"
    # The trailing list must NOT be empty: rva 0x6ba970 (lobby slot gather, from
    # the 0x204C handler) reads its first element unchecked -> access violation
    # at 0x6bac36. EXPERIMENT: [champion variant] (probably the chosen skin).
    tail = (struct.pack("<IQI", 0, 0, 0) + string_info("") + pack_compact(0)
            + struct.pack("<I", 0) + pack_compact(1) + struct.pack("<I", champion))
    return (b"\x00" + s
            # player id must equal the client's local id (global 0x17579f0): 0
            # without a 0xCE character entry, else the entry's id.
            + struct.pack("<IIQ", TEAM_NUMBER, 0, LOCAL_PLAYER_ID if SEND_CHARACTER_ENTRY else 0) + string_info(name)
            + b"\x00" + struct.pack("<II", champion, 0) + b"\x00"
            + struct.pack("<II", ROOM_ID, 1) + struct.pack("<7I", *([0] * 7))
            + tail)


QUEUE_STATE = {}


def pack_compact(value):
    """Turbine packed uint (reader rva 0x21430): <0x80 1 byte; <0x4000 2 bytes
    (0x80|hi, lo); <0x20000000 4 bytes (0xC0|b3, b2, u16 LE low); else 0xE0 + u32."""
    if value < 0x80:
        return bytes([value])
    if value < 0x4000:
        return bytes([0x80 | (value >> 8), value & 0xFF])
    if value < 0x20000000:
        return bytes([0xC0 | (value >> 24), (value >> 16) & 0xFF]) + struct.pack("<H", value & 0xFFFF)
    return b"\xE0" + struct.pack("<I", value)


def build_message(dest_id, event_id, event_body, flags=0x02):
    """Game message frame (frame header bit 0x02, parser rva 0x70af10;
    outgoing builder rva 0x70f380):
      u32 len | u8 0x02 | u64 dest | u8 flags | compact event_id | event body
    Event body = u8 base header (rva 0x70d380) + event-specific fields.
    flags bit 0x02 lets the message past the client's delivery gate (rva
    0xbe1b50) while it is still loading; without it messages are dropped."""
    frame = (b"\x02" + struct.pack("<Q", dest_id) + bytes([flags])
             + pack_compact(event_id) + event_body)
    return struct.pack("<I", len(frame)) + frame


# Event IDs (registry calls to rva 0x70ec50; names from handler strings)
EVT_MASTER_CHARACTER_LIST = 0x209D  # GM_Character.RecvNotice_MasterCharacterListReceived
EVT_DELIVER_ENCOUNTER_INFO = 0x2024  # gmCEncounterManagementSystem::RecvEvt_DeliverEncounterInfo
EVT_UPDATE_ENCOUNTER_INFO = 0x20FF   # ...RecvEvt_UpdateEncounterInfo (4 arrays; needs a prior 0x2024)
EVT_CHAMPION_DATA = 0x20ED           # sets loading-screen bit 2 (handler rva 0x6833d0); real name unknown
# (0x215A was previously mislabeled as DeliverEncounterInfo; it targets a game object.)

EVT_ACCOUNT_CHARACTER_SET = 0xCE     # sets loading-screen bit 8; real name unknown
EVT_SET_LOCAL_PLAYER = 0xEB # handler rva 0x298a90 -> listeners' slot +0x20 (objmgr rva 0x24b2e0)

# Client-side services are event receivers registered in the dispatcher map
# (base dispatch rva 0x70d9c0, map at dispatcher+0x68) under ids
# 0x06000000_000004xx (table at rva 0x1454460). The player/character system
# (ctor rva 0x2a8090, GetID vfunc +0x18 = rva 0x2a8100) is ...0403; it handles
# both 0xEB and 0x209D (QI rva 0x561d20 / 0x2a82c0).
SVC_PLAYER_SYSTEM = 0x0600000000000403
# Game-object ids: top byte must be 1,2,3,4,5,0x0B or 0x81 (rva 0xdaf90);
# top byte 2 = player (rva 0xdaf10).
LOCAL_PLAYER_ID = 0x0200000000000001
# The object descriptor's first u32 is a data id (DID) naming the entity
# definition (WorldEntityFactory, rva 0x14ad90 / 0x14f1f0): prefix 0x2d =
# .entity (accepted as-is), prefix 0x2e = world state (.wc) whose record names
# its parent .entity. 0 is "invalid" and makes creation fail silently.
# EXPERIMENT: a generic base entity; the real player entity DID is unknown.
PLAYER_ENTITY_DID = 0x2D000002
CREATE_PLAYER_OBJECT = False
ACCOUNT_LEVEL = 30
ENCOUNTERS = [
    (0x4000013E, "Gotham Heights"),
    (0x40000270, "Coast City"),
    (0x4000039C, "Crisis Labs: Coast City Variant"),
    (0x40000399, "Gotham Divided"),
    (0x40000E68, "Crime Alley Clash: 1v1"),
    (0x40000E74, "Crime Alley Clash: 2v2"),
    (0x40000EC0, "Apokolips Causeway Clash: 1v1"),
    (0x40000C28, "Metropolis Skyway"),
    (0x40000C82, "Crime Alley v AI"),
    (0x40000B6C, "Gotham Heights v AI"),
    (0x40000B6A, "Coast City v AI"),
    (0x40000B6B, "Gotham Divided v AI"),
    (0x40000991, "Tutorial -- Basic"),
    (0x40000A81, "Tutorial -- Intermediate"),
    (0x40000CA6, "Crime Alley: 1vAI Tutorial"),
]
# [{"name", "id", "costumes": [ids]}] for all 43 champions defined in the packs.
import json
with open(os.path.join(SERVER_DIR, "champions.json"), encoding="utf-8") as _f:
    ROSTER = json.load(_f)


# u8 base | empty table (u8 size class | compact count 0)
EMPTY_TABLE_EVENT = b"\x00" + b"\x00" + b"\x00"


def build_batch(sub_events):
    """Batch event 0x4 body (serializer rva 0x47770): u8 base | compact count |
    per sub-event: compact event id | u32 length | sub-event body (the
    sub-event body has NO leading base byte)."""
    out = b"\x00" + pack_compact(len(sub_events))
    for event_id, body in sub_events:
        out += pack_compact(event_id) + struct.pack("<I", len(body)) + body
    return out


# Where the tutorial avatar spawns. The tutorial map pack loaded at match start
# (0xa0c112ca) holds landblock records 0x80RRXXYY for region 1, x 0x12-0x14,
# y 0xca-0xcc -> centre landblock (0x13, 0xcb). EXPERIMENT: cell 0, middle of the
# block. The renderer (SmartBox, global rva 0x1773518) only draws once its
# viewer Position (+0x50) is valid: region (+4) != 0, landblock bytes (+8/+9)
# != 0xff, cell (+0xa) != 0xffff (check rva 0x3d16a0); the first rendered frame
# posts native notice 0xb -> 0x696af0 clears pending bit 4 (+20% loading).
# Spawn: (region, landblock x, landblock y, cell, x, y, z). The tutorial map's
# geometry sits in landblock (0x14, 0xcb): map entities at x 16..82, y 10..42,
# ground z ~ 200.0 (read from live physics objects); z 0 is the red Bleed far
# below. The client merges a received position by 0xB0 sub-flag (rva
# 0x17da90): 0x08 copies ONLY region/landblock/cell, 0x04 copies origin x/y,
# 0x02 copies origin z -- so a full placement needs sub-flags 0x0E with the
# origin floats inside the Position (flag 0x10). Override live with
# logs/spawn.txt ("region lbx lby cell x y z"; lbx/lby/cell hex).
# The pathfinder only has nav info (record 0x850113cb) for landblock (0x13,0xcb):
# navigable street there spans roughly x 16..155, y 18..64, z ~200 (probed
# with navprobe.py). Clicks/positions in (0x14,0xcb) -- the cinematic's plaza
# -- are rejected by the client ("no nav record for landblock", rva 0xfa91d).
# (18.7, 60.4) = where the intro cinematic 0x35000026 ends its final pan (camera
# (12.17, 53.88, 215.2) minus the gameplay camera offset (-6.55, -6.55, +14.66)).
# Old test spawn on the bridge: (60.0, 44.5, 200.2).
SPAWN_POSITION = (1, 0x13, 0xCB, 0, 18.7, 60.4, 200.3)
# Tutorial pack 0xa0000256 holds camera/cinematic records 0x35000025/26/28/33/34
# (DID prefix 0x35 = data type 0x3e). 0x35000026 = the INTRO (burning plaza,
# base, streets; verified against the reference video 2026-10-05).
# 0x35000025 = Batman walks up to a tower rising from the ground at the base
# (probably the tutorial's ending).
CINEMATIC_DID = 0x35000026
MATCH_OBJECTS_DELAY = 4.0   # seconds after the client's ConnectToLobby (0x20F2)
CINEMATIC_DELAY = 5.0   # seconds after the client's load-complete notice (curtain-up time)
MOVEMENT_MODULE_SEQ = 1    # 0xB0 flag 0x20 part, see build_create_object
MOVEMENT_MODULE_TYPE = 1   # rigid-body character replay (server-driven)
# The champion the player controls is a SEPARATE object. The player's property
# 0x100000cf (controlled agent IID) must name it: listener rva 0x60a570 sets
# byte [charsys+0x100] only when that IID is non-zero and NOT the player's own
# id, and the UI graph's "player ready" condition (rva 0x6b5200) needs that
# byte plus the agent entity placed in the world before it loads the HUD.
# 0x100005e8 is a second player->entity IID link (rva 0x45c150, input path).
CHAMPION_AGENT_ID = 0x0200000000000002
# 0x2053 "Start" sets the client's "match started" byte ([0x1777138]+0xac, read in
# ~80 places). It is the only native way to open the dialog manager's gate (bit 4
# of +0x14c, set at ServerLoadComplete) so that conversations play, BUT with it
# the client crashes ~2 s into the world load (2026-10-05):
#   1. rva 0x159507: smooth movement branch sets an animation variable on a table
#      that is not initialised yet -> avoided by sending the second sequence byte
#      as 0 until the client reports load complete (QUEUE_STATE["in_world"]);
#   2. then a NULL virtual call at rva 0x7dbf7e (fn 0x7dbef0, worker thread; stack
#      1d9931 7dc5b2 7de0c7 5fefe0 838d10; looks like audio) -> NOT solved.
# Sent in-world it throws the UI back into the world-load transition.
SEND_MATCH_START = False
PROP_CONTROLLED_AGENT = 0x100000CF
PROP_PLAYER_ENTITY_LINK_2 = 0x100005E8


def current_module():
    """(sequence, type) of the movement module; logs/module.txt "seq type"
    overrides it live (a new sequence makes the client swap modules, 0x153e70)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "module.txt")
    try:
        p = open(path).read().split()
        return int(p[0]) & 0xFF, int(p[1]) & 0xFF
    except (OSError, ValueError, IndexError):
        return MOVEMENT_MODULE_SEQ, MOVEMENT_MODULE_TYPE


def current_spawn():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "spawn.txt")
    try:
        p = open(path).read().split()
        return (int(p[0]), int(p[1], 16), int(p[2], 16), int(p[3], 16),
                float(p[4]), float(p[5]), float(p[6]))
    except (OSError, ValueError, IndexError):
        return SPAWN_POSITION


_TELEPORT = {}


def teleport_sequence(position, key="champion"):
    """Sequence byte (per object) that changes whenever that object's spawn position changes."""
    st = _TELEPORT.setdefault(key, {"pos": None, "seq": 0})
    if position != st["pos"]:
        st["pos"] = position
        st["seq"] = st["seq"] % 250 + 1
    return st["seq"]


def build_position(region, lb_x, lb_y, cell, x, y, z):
    """Position (reader rva 0x7c610): u8 flags | [0x01: u8 region, or 1 when
    0x40] | [0x02: u8 landblock x, u8 landblock y] | [0x04: u16] | [0x08: u16
    cell, or default when 0x80; else 0xffff = invalid] | [0x10: f32 x, y, z --
    only for Position classes that have an origin] | [0x20: quaternion]."""
    flags = 0x02 | 0x08 | 0x10
    out = b""
    if region == 1:
        flags |= 0x01 | 0x40
    else:
        flags |= 0x01
        out += bytes([region])
    return bytes([flags]) + out + bytes([lb_x, lb_y]) + struct.pack("<H", cell) + struct.pack("<fff", x, y, z)


def pack_property_id(prop_id):
    """Packed property id (reader rva 0xfc420)."""
    if 0x10000000 <= prop_id < 0x10004000:
        return bytes([0x40 | ((prop_id >> 8) & 0x3F), prop_id & 0xFF])
    if prop_id < 0x4000:
        return bytes([prop_id >> 8, prop_id & 0xFF])
    return b"\x80" + struct.pack("<I", prop_id)


# Property value kinds (def+0xc; value readers rva 0x107d60 / 0x107590):
# 7 = IID (u64), 9 = f32, 0x0e = StringInfo, 0x10 = compact int, 0x13 = u32
# enum, 0x15 = DID (u32). Look a property up live with propdef.py.
def pack_property(prop_id, kind, value):
    out = struct.pack("<I", prop_id) + pack_property_id(prop_id)
    if kind == 7:
        return out + struct.pack("<Q", value)
    if kind == 8:
        # enum / data id (reader rva 0xfeb20): u8 top byte | compact low 24 bits
        return out + bytes([value >> 24]) + pack_compact(value & 0xFFFFFF)
    if kind == 9:
        return out + struct.pack("<f", value)
    if kind == 0x0E:
        return out + string_info(value)
    if kind == 0x10:
        return out + pack_compact(value)
    if kind in (0x13, 0x15):
        return out + struct.pack("<I", value)
    if kind == 0x16:
        return out + bytes([1 if value else 0])   # bool: one byte (reader rva 0x107da2 -> 0x49520)
    raise ValueError(f"property kind {kind:#x} not supported")


def facing_yaw(heading):
    """Model yaw (radians, wrapped to [-pi, pi]) that faces the heading of travel."""
    import math
    yaw = heading - math.pi / 2
    return (yaw + math.pi) % (2 * math.pi) - math.pi


def build_create_object(object_id, class_id=0, unknown64=0, sequence=1, position=None, iid_properties=None,
                        heading=0.0, speed=0.0, tele_seq=1, properties=None):
    """Object creation bundle, sent as batch 0x4 addressed to the NEW object's
    id (router rva 0x24e070 -> 0x24ab70 -> 0x24bd30 -> 0x24d8a0 -> 0x24ca10 ->
    entity factory rva 0x207dc0). Needs the local player id to be set first
    (event 0xEB). Sub-events:
      0xF2 descriptor (serializer rva 0x45970 / 0x14bd00):
           u32 entity DID (desc+8) | u64 (desc+0x38) | u32 (compared with obj+0x110)
      0xB0 position (rva 0x45430 / 0x17ee90): u8 flags | [optional
           parts by flag bit: 0x20 movement module, 0x04 parent u64, 0x10 bool,
           0x08 table, 0x40/0x02 motion, 0x80 extra]. REQUIRED: without a 0xB0
           in the batch the client silently refuses to create the object
           (rva 0x249230).
      0xBC properties (rva 0x45450): property table.
    """
    # NOTE: sub-events inside a batch carry NO base header byte (verified:
    # with one, the client read the DID shifted by a byte).
    descriptor = struct.pack("<IQI", class_id, unknown64, sequence)
    if position:
        region, lb_x, lb_y, cell, x, y, z = position
        # Flag 0x20 part (rva 0x17e410): u8 module sequence (0 = none) | u8
        # MOVEMENT MODULE TYPE | [flag 0x01: u64]. Handler 0x153e70 creates the
        # entity's movement module from it (type registry: 1 = "ClientRigid
        # BodyCharacterReplayMovementModule", also 2, 3, 9). Without a module
        # nothing consumes the motion queue: the module's init (0x20a340) and
        # update (0x20b5f0) are what teleport the entity into the world
        # (PhysicsComponent::SetPosition 0x171af0 -> "in world" flag).
        # Flag 0x40 part (rva 0x17e530): u8 sub-flags (0x01 f64 timestamp, same
        # clock as our 0x01000000 time packets; 0x08 Position on the wire and
        # "take landblock/cell"; 0x04 / 0x02 "take origin x,y / z"), then
        # ALWAYS a u16 (time offset ticks). (Flag 0x02 part, not sent: u8
        # header | bit 0: i16 x, i16 y | bit 1: i16 z = small origin offsets
        # in 1/1024 units, rva 0x17dd70.)
        # The motion queue (rva 0x1525a0) DROPS a new sample whose heading
        # and (zero) velocity match the previous one -- a bare position change
        # is ignored. A jump needs the teleport sequence byte to change:
        # flag 0x02 part header bit 0x800 (header = u8 0x80 marker | u8 high
        # 0x08) -> u8 sequence (state+0x62 -> sample+8; the module compares
        # it, rva 0x209af0, and hard-teleports).
        # Motion header fields used (merge rva 0x17da90): bit 0x04 f32 heading
        # of travel (radians), 0x20 f32 speed (velocity = speed * (cos, sin)
        # of the heading), 0x200 "facing = heading", 0x800 u8 teleport
        # sequence. Header = u8 low (0x80 = high byte follows) | u8 high.
        module_seq, module_type = current_module()
        position = (bytes([0x62, module_seq, module_type, 0x0F])
                    + struct.pack("<d", time.time())
                    + build_position(region, lb_x, lb_y, cell, x, y, z) + struct.pack("<H", 0)
                    # Header bit 0x1000 = a second sequence byte (state+0x63 ->
                    # sample+9). The replay module (rva 0x20b5f0) treats a 0 there
                    # as "changed" EVERY frame (0x209af0) and hard-teleports instead
                    # of taking its smooth branch, which is the one that feeds the
                    # animation variables (0x2097e0: floats 0x1f1 / 0x300 / 0x501).
                    # Facing: the model's forward axis at yaw 0 is +y (verified live),
                    # while the heading of travel is measured from +x, so "facing =
                    # heading" (bit 0x200) leaves him 90 degrees off. Send the explicit
                    # yaw instead (bit 0x08: i16 in 1e-4 rad) = heading - pi/2.
                    + bytes([0x80 | 0x2C, 0x18]) + struct.pack("<ff", heading, speed)
                    + struct.pack("<h", int(round(facing_yaw(heading) * 10000.0)))
                    # Second sequence byte: 0 (= hard teleports, no animation
                    # variables) until the client reports the load complete. In
                    # "match started" mode (0x2053) the smooth branch crashed during
                    # loading: 0x2097e0 -> 0x18f3d0 -> 0x1594c0 walked an animation
                    # variable table that was not initialised yet (rva 0x159507).
                    + bytes([tele_seq, 1 if QUEUE_STATE.get("in_world") else 0]))
    else:
        position = bytes([0]) + struct.pack("<H", 0)
    # Property table (reader rva 0x103330 -> 0x1025d0): u8 size class |
    # compact count | entries: u32 property id | packed id again (0x109740 /
    # 0xfc420) | value by the property's kind (kind 7 = IID = raw u64).
    entries = [(prop_id, 7, iid) for prop_id, iid in (iid_properties or {}).items()] + list(properties or [])
    properties = bytes([0]) + pack_compact(len(entries))
    for prop_id, kind, value in entries:
        properties += pack_property(prop_id, kind, value)
    body = build_batch([(0xF2, descriptor), (0xB0, position), (0xBC, properties)])
    return build_message(object_id, 0x4, body)


# Server-side champion movement. Positions are kept in the frame of the spawn
# landblock (x, y may run past 0..160; the client normalises). The client's
# move order is event 0x20EE to service 0x0600000000000008: u32 command (4 =
# move to point, 3 = attack-move) | u64 target iid | u32 | Position (flags,
# landblock, f32 x, y, z) | u8.
MOVE_SPEED = 6.0
MOVE_HZ = 60               # position updates per second while walking (was 10 until 2026-10-05)
MOVER = {"spawn": None, "pos": None, "target": None, "heading": 0.0, "speed": 0.0, "last": 0.0}
MOVER_LOCK = threading.Lock()
USER_SEND_LOCK = threading.Lock()


def send_user(msg):
    user = QUEUE_STATE.get("user_conn")
    if user is None:
        return
    with USER_SEND_LOCK:
        user.sendall(msg)


def mover_state():
    """Current (spawn tuple with live x, y, z), heading, speed, teleport seq."""
    spawn = current_spawn()
    with MOVER_LOCK:
        if spawn != MOVER["spawn"]:          # first use, or logs/spawn.txt changed: jump there
            MOVER.update(spawn=spawn, pos=list(spawn[4:7]), target=None, speed=0.0)
        x, y, z = MOVER["pos"]
        heading = MOVER["heading"]
        # Live experiment: logs/heading.txt (radians) forces the heading while standing.
        if MOVER["target"] is None:
            try:
                heading = float(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                  "logs", "heading.txt")).read().split()[0])
            except (OSError, ValueError, IndexError):
                pass
        return spawn[:4] + (x, y, z), heading, MOVER["speed"], teleport_sequence(spawn)


def parse_client_position(buf, pos=0):
    """Inverse of build_position; returns (region, lb_x, lb_y, x, y, z) or None."""
    flags = buf[pos]; pos += 1
    region = 0
    if flags & 0x01:
        if flags & 0x40:
            region = 1
        else:
            region = buf[pos]; pos += 1
    if not flags & 0x02:
        return None
    lb_x, lb_y = buf[pos], buf[pos + 1]; pos += 2
    if flags & 0x04:
        pos += 2
    if flags & 0x08 and not flags & 0x80:
        pos += 2
    if not flags & 0x10:
        return None
    x, y, z = struct.unpack_from("<fff", buf, pos)
    return region, lb_x, lb_y, x, y, z


def mover_order(body):
    """Handle a 0x20EE move order: set the walk target."""
    if len(body) < 17:
        return
    command = struct.unpack_from("<I", body, 0)[0]
    if command not in (3, 4):
        return
    target = parse_client_position(body, 16)
    spawn = current_spawn()
    if not target or target[0] != spawn[0]:
        return
    with MOVER_LOCK:
        if MOVER["pos"] is None:
            return
        MOVER["target"] = [(target[1] - spawn[1]) * 160.0 + target[3],
                           (target[2] - spawn[2]) * 160.0 + target[4], target[5]]
    log_line(f"    move order {command}: target lb {target[1]:02x}{target[2]:02x} ({target[3]:.1f}, {target[4]:.1f}, {target[5]:.1f})")


def mover_tick():
    """Advance the walk; returns True when an update should be sent."""
    import math
    now = time.time()
    with MOVER_LOCK:
        dt = min(now - MOVER["last"], 0.25) if MOVER["last"] else 0.0
        MOVER["last"] = now
        if MOVER["target"] is None or MOVER["pos"] is None:
            return False
        px, py, pz = MOVER["pos"]
        tx, ty, tz = MOVER["target"]
        dx, dy = tx - px, ty - py
        dist = math.hypot(dx, dy)
        step = MOVE_SPEED * dt
        if dist <= max(step, 0.05):
            MOVER.update(pos=[tx, ty, tz], target=None, speed=0.0)
            MOVER["arrived"] = True
        else:
            k = step / dist
            MOVER["heading"] = math.atan2(dy, dx)
            MOVER["speed"] = MOVE_SPEED
            MOVER["pos"] = [px + dx * k, py + dy * k, pz + (tz - pz) * k]
        return True


def mover_thread():
    while True:
        time.sleep(1.0 / MOVE_HZ)
        try:
            if QUEUE_STATE.get("avatar_seq") and mover_tick():
                send_user(build_match_objects(sequence=QUEUE_STATE["avatar_seq"]))
                if MOVER.pop("arrived", False) and at_tutorial_target():
                    for label, msg in tutorial_arrived():
                        log_line(f"--- sent {label}")
                        send_user(msg)
        except OSError:
            pass


# What the HUD script reads from the controlled agent with
# PropertySystem.InqProperty (class ControlledAgentDispatcher and the portrait
# / character panel): ids from emp_gen.gm*PropertyList (tools/ui_properties.json).
CHAMPION_PROPERTIES = [
    (0x10000064, 7, LOCAL_PLAYER_ID),        # Character_ControllableAgentToPlayer_InstanceID
    # Lighting environment, also on the agent: at the end of the intro cinematic
    # the client re-evaluates the environment and gets the default (dark) for
    # ~2.5 s before the player object's 0x956 is picked up (envwatch.py log,
    # 2026-10-05); the guess is that the "local player" lookup resolves to the
    # controlled agent at that moment. EXPERIMENT.
    (0x00000956, 8, 0x10000016),
    # EXPERIMENT 2026-10-05 (darkness): the champion's fog-of-war component
    # (entity handle +0x88, vtable 0x12098e8, update 0x6b3520) takes its reference
    # entity from ITS OWN entity's property 0x100000cf (0x69de00 -> 0x45d620).
    # Our agent had none, so the component never updated (last-update time -1)
    # and nothing is ever revealed -> the world stays black once fog of war is
    # on. Point it at itself.
    # (0x100000CF, 7, 0x0200000000000002)  -- self link: resolved the reference
    # entity but the component stays inert (it is only activated on the LOCAL
    # PLAYER's entity, gate at rva 0x6add80), so it was removed again.
    (0x1000009C, 0x10, TEAM_NUMBER),         # PVP_Team
    # LIFE STATE (2026-10-05 night): the vitals component tracks property
    # 0x100000fa in its slot +0x20 (id +0x28, value +0x2c, "unset" byte +0x34).
    # Unset -> 0x56e9c0 reports the caller's default (0) and the nameplate
    # builder 0x650a70 skips the entity (needs Alive = 4; enum DeadAndFaded 1,
    # Dead 2, Incapacitated 3, Alive 4, Respawning 5). Listener 0x680e61 reads
    # it as kind 8/0xa. The player object is left unset on purpose (it is the
    # second, gliding Batman and must not get a nameplate). EXPERIMENT.
    (0x100000FA, 8, 4),                      # LifeState = Alive
    (0x10000167, 0x10, 1),                   # Level
    (0x10000142, 0x10, 0),                   # XP
    (0x100001AF, 0x10, 1),                   # SkillPoints
    (0x1000035E, 9, 0.0),                    # Upgrade_Currency
    (0x000003CE, 0x0E, "Gaslight Batman"),   # Name
    (0x10000433, 0x0E, "Gaslight Batman"),   # Character_Name
    (0x10000384, 0x15, 318767845),           # Character_SmallIcon (champions.json tex384)
    (0x10000338, 0x15, 318767845),           # Character_ConsoleVitals_Portrait (guess: same icon)
    (0x10000337, 0x15, 318767845),           # Character_LargeIcon (guess: same icon)
]


# The scene's lighting environment (scene controller [[0x1773518]+0xdc], type at
# +0x11c) is chosen by rva 0x3e35c0 from the LOCAL PLAYER's properties 0x956 /
# 0x5cc / 0x216, else from the region property 0x216 at the viewer position,
# else the default 2 -- and the default is a nearly black scene. After the intro
# cinematic 0x35000026 the client fell back to 2 ("dark world"); after cinematic
# 0x35000025 it was 0x10000016 and normally lit (snapshot diff, 2026-10-05).
PLAYER_PROPERTIES = [
    (0x00000956, 8, 0x10000016),             # lighting environment type (EXPERIMENT)
    # MINIMAP IMAGE (disassembly 2026-10-05): the map manager attaches a property
    # listener for 0x100001d3 (= encounter DID, kind 0x15) to the LOCAL PLAYER
    # object (rva 0x60cbc0 -> 0x18ba40). On a change (listener 0x66a8e0) it
    # resolves the encounter's 0x49 twin, reads its 0x10000287 (Tutorial 1:
    # 0x48000d3e, pack 0xa00000b3), loads it and invokes
    # GM_MapManager.RecvNotice_DeliverMapData(image DID) (rva 0x64c2c0 ->
    # 0x49f4c0). Without it the minimap stays the green placeholder. EXPERIMENT.
]
# Sent only on RESENDS (sequence >= 2): the map manager attaches its 0x100001d3
# listener when the local player object appears (trace 23:09:32), i.e. after the
# create bundle's properties were applied, so the value must CHANGE afterwards.
# The 2 s game-connection keepalive resends the bundle with a higher sequence.
PLAYER_LATE_PROPERTIES = [
    (0x100001D3, 0x15, 0x40000991),          # current encounter (Tutorial 1)
]


CHAMPION_AGENT_CLASS = 0x40000086   # Gaslight Batman variant (EXPERIMENT; was TUTORIAL_AVATAR 0x2E0001B2)


def build_match_objects(sequence=1, link_agent=True):
    """The champion agent and the player object (both Gaslight Batman's world
    state for now, co-located; STOPGAP until the real player entity is known)."""
    spawn, heading, speed, tele = mover_state()
    links = ({PROP_CONTROLLED_AGENT: CHAMPION_AGENT_ID, PROP_PLAYER_ENTITY_LINK_2: CHAMPION_AGENT_ID}
             if link_agent else {})
    # The game-level components (vitals 0x69d420, skills, ...) are only attached
    # (rva 0x69d7a0) when the object's descriptor DID has data type 0x40 = a
    # champion VARIANT record (prefix 0x40), not a bare world state (0x2E).
    return (build_create_object(CHAMPION_AGENT_ID, class_id=CHAMPION_AGENT_CLASS, position=spawn, sequence=sequence,
                                heading=heading, speed=speed, tele_seq=tele, properties=CHAMPION_PROPERTIES)
            + build_create_object(LOCAL_PLAYER_ID, class_id=PLAYER_AVATAR, position=spawn,
                                  sequence=sequence, iid_properties=links,
                                  properties=PLAYER_PROPERTIES + (PLAYER_LATE_PROPERTIES if sequence >= 2 else []),
                                  heading=heading, speed=speed, tele_seq=tele))


# ---- Tutorial HUD / objectives -------------------------------------------
# In a tutorial the HUD starts with every element hidden; the server reveals
# elements with event 0x213d (serializer rva 0x43f5d0, handler 0x6368b0 ->
# GM_UI.RecvNotice_NotifyHUDElement): u8 base | u32 element | u32 event |
# u32 highlight | u32 highlight item DID. These events (and 0x2034 / 0x2009)
# must be addressed to a game OBJECT (the local player), not a service.
HUD_PLAYER_VITAL_BARS, HUD_CONVERSATION, HUD_SKILLS_BAR, HUD_MINIMAP = 2, 3, 14, 15
HUD_PORTRAIT, HUD_MISSION_OBJECTIVES = 18, 35
HUD_EVENT_FIRST_RESTORED, HUD_EVENT_HIDE, HUD_EVENT_SHOW_HIGHLIGHT, HUD_EVENT_OPEN = 1, 2, 7, 11


def build_hud_element(element, event, highlight=0, highlight_did=0):
    return build_message(LOCAL_PLAYER_ID, 0x213D,
                         b"\x00" + struct.pack("<IIII", element, event, highlight, highlight_did))


def build_objective(objective_id, text=None, active=None, state=None, count=None, count_max=None,
                    category=None, sort_order=None, optional=None, banner=None):
    """Objective struct (serializer rva 0x472330): u32 flags, then the fields
    whose flag bit is set, in wire order: bit5 u32 id | bit15 u32 state |
    bit0 u32 category | bit7 StringInfo text | bit4 u32 count | bit2 u32 count
    max | bit14 u32 sort order | bit19 u8 active | bit8 u8 optional (other
    bits: see memory notes). The tracker script only shows objectives that sit
    in a delivered, visible category."""
    flags, out = 0x20, struct.pack("<I", objective_id)
    if state is not None:
        flags |= 0x8000; out += struct.pack("<I", state)
    if category is not None:
        flags |= 0x01; out += struct.pack("<I", category)
    if text is not None:
        flags |= 0x80; out += string_info(text)
    if count is not None:
        flags |= 0x10; out += struct.pack("<I", count)
    if count_max is not None:
        flags |= 0x04; out += struct.pack("<I", count_max)
    if sort_order is not None:
        flags |= 0x4000; out += struct.pack("<I", sort_order)
    if active is not None:
        flags |= 0x80000; out += bytes([1 if active else 0])
    if optional is not None:
        flags |= 0x100; out += bytes([1 if optional else 0])
    if banner is not None:
        # bit24 StringInfo (+0xbc, LAST field on the wire) = the top-centre banner
        # line (script ObjectiveBannerDisplay, i_siBannerText). bit11 (+0x88) is
        # only an alternate text for another team relationship -- it was tried
        # as the banner first and showed nothing.
        flags |= 0x1000000; out += string_info(banner)
    return struct.pack("<I", flags) + out


def build_objective_category(category_id, title, description="", sort_order=0, state=None, visible=True):
    """Category struct (serializer rva 0x463570): u32 flags | bit0 u32 id |
    bit3 u32 (+0x54, state?) | bit4 StringInfo title | bit1 StringInfo
    description | bit2 u32 (+0x50, sort order?) | bit5 u8 visible."""
    flags, out = 0x01, struct.pack("<I", category_id)
    if state is not None:
        flags |= 0x08; out += struct.pack("<I", state)
    # Which of the two strings the tracker shows as the heading is not settled
    # (title alone displayed "undefined"), so an empty description repeats the title.
    flags |= 0x10; out += string_info(title)
    flags |= 0x02; out += string_info(description or title)
    flags |= 0x04; out += struct.pack("<I", sort_order)
    flags |= 0x20; out += bytes([1 if visible else 0])
    return struct.pack("<I", flags) + out


def build_objective_list(objectives, categories=()):
    """0x2034 (serializer rva 0x43bf30 -> 0x477300, handler 0x6803e0): u8 base |
    u32 n + objectives | u32 m + categories."""
    body = (b"\x00" + struct.pack("<I", len(objectives)) + b"".join(objectives)
            + struct.pack("<I", len(categories)) + b"".join(categories))
    return build_message(LOCAL_PLAYER_ID, 0x2034, body)


# Objective states (script emp_gen ObjectiveStateList): 0 undefined, 1 failed,
# 2 completed, 4 near completion, 5 / 6 team 2 / team 1 won.
OBJECTIVE_COMPLETED = 2
# Category states (emp_gen ObjectiveCategoryStateList): 0 undefined, 3 / 4 team
# 2 / 1 won, 5 completed, 6 failed, 7 remove, 8 SHOW, 9 hide. The tracker's
# CategoryDisplay.UpdateShow() makes a category visible ONLY in state 8; with
# the state left at 0 the tracker opens but draws nothing (verified live
# 2026-10-05 with flashcall.py).
OBJECTIVE_CATEGORY_SHOW = 8
TUTORIAL_OBJECTIVE_TEXTS = {
    1: "<font color='#FFFF00'>Right-click</font> on the marked location to move there<br>(Follow the arrows at your Champion's feet)",
    2: "<font color='#FFFF00'>Right-click</font> the drone to <font color='#00FF00'>Basic Attack</font> and defeat it",
}


def tutorial_objective(objective_id, active, state=None):
    return build_objective(objective_id, text=TUTORIAL_OBJECTIVE_TEXTS[objective_id], active=active, state=state,
                           category=1, sort_order=objective_id - 1, optional=False,
                           banner=TUTORIAL_OBJECTIVE_TEXTS[objective_id])


def tutorial_objectives():
    # Only the first objective is delivered up front: with a second, INACTIVE
    # objective in the list the tracker did not show at all (2026-10-05).
    # EXPERIMENT: the second one is introduced with 0x2009 on arrival.
    return build_objective_list(
        [tutorial_objective(1, True)],
        [build_objective_category(1, "A Champion in Peril", state=OBJECTIVE_CATEGORY_SHOW)])


def build_objective_update(objective):
    """0x2009 (serializer rva 0x43bf50, handler 0x684330): update ONE existing
    objective: u8 base | u32 id | objective struct. Dest = the player object."""
    objective_id = struct.unpack_from("<I", objective, 4)[0]
    return build_message(LOCAL_PLAYER_ID, 0x2009, b"\x00" + struct.pack("<I", objective_id) + objective)


def build_start_conversation(key, instance_id=0xFFFFFFFF, speaker=CHAMPION_AGENT_ID):
    """0x2001 StartConversation (serializer rva 0x4453a0, handler 0x613b90), to the
    player object: u8 base | u64 IID (unused in mode 1) | u32 mode (1 = the
    encounter's conversation table, DID 0x40000cb7 for Tutorial 1) | u32 key |
    u32 n + u64[n] participant IIDs (n must equal the conversation's participant
    count, 1 for all tutorial ones) | u8 1 | u32 instance id (0xFFFFFFFF = none;
    else the client sends event 0x2140 with it when the conversation ends).
    The client plays the lines itself: portrait panel, voice, chat-log caption.
    All keys and lines: tools/conversations_tutorial1.txt."""
    body = (bytes(1) + struct.pack("<QIII", 0, 1, key, 1) + struct.pack("<Q", speaker)
            + bytes([1]) + struct.pack("<I", instance_id))
    return build_message(LOCAL_PLAYER_ID, 0x2001, body)


def build_tutorial_hint(hint_id, force_open=True):
    """Left-side hint panel. Generic notice event 0x2 to the player object:
    u8 base | u32 notice id | u32 blob length | blob. Notice 0x1000027f
    ShowTutorialHint: blob = u32 hint id | u8 force open (-> GM_Tutorial.
    RecvNotice_UI_ShowTutorialHint; the client resolves icon and texts from hint
    table 0x4800070c). 0x100004a5 CloseTutorialHint: blob = u32 hint id.
    Hint ids: 16 Guide Arrows, 17 Basic Attack, 18 Experience, 19 Quick Upgrade,
    20 Will, 21 Skill Ranks, 28 Attack-move, 34 Skill Points, 38 Tactical
    Skills, 40 Status Icons. Needs HUD element 32 (HintManager) revealed."""
    blob = struct.pack("<I", hint_id) + bytes([1 if force_open else 0])
    return build_message(LOCAL_PLAYER_ID, 0x2, bytes(1) + struct.pack("<II", 0x1000027F, len(blob)) + blob)


HINT_GUIDE_ARROWS, HINT_BASIC_ATTACK, HINT_WILL = 16, 17, 20


def conversations(*keys):
    return [(f"conversation {k:#x} (0x2001)", build_start_conversation(k)) for k in keys]


# Tutorial 1 script so far (reference video, memory note ic-tutorial1-reference-
# video): what happens each time the champion completes a walk. (EXPERIMENT:
# any completed move counts; markers / drones are not spawned yet.)
#   step -> (conversation keys, next objective text or None)
# Where the guide ping stands for each step (landblock (0x13,0xcb) x, y, z;
# positions taken from the intro's final shots / the first-drone cinematic,
# not from the original server). Reaching it (within TARGET_RADIUS) completes
# the step. One ping object is reused: it is teleported to the next target.
TUTORIAL_TARGETS = {
    1: (36.0, 57.5, 200.0),
    2: (44.0, 58.5, 200.0),
}
TARGET_RADIUS = 2.5
PING_OBJECT_ID = 0x0200000000000030
PING_CLASS = 0x40000A9C       # "Map Ping" (pack 0xa00000b3): the client draws the green
                              # guide arrows at the champion's feet toward this entity


# Properties on the ping entity (object bundle 0xBC). Minimap note (map manager
# 0x64b150, verified in disassembly): the entity needs bool 0x100007d8 (or
# 0x10000a95) TRUE, then icon 0x10000083 / category 0x100004da come from the
# record's twin 0x49000a9c and team 0x1000009c keeps it from being filtered as an
# enemy note. The ground-marker VFX is run by scriptlet 0x34000600 on the ping;
# which properties switch it on is INFERRED from the script's variable table
# (UseVFX / UseAlert / PlayerIID): bools 0x10000b96 / 0x10000b97 and IID
# 0x10000029 / 0x10000155 = the champion -- EXPERIMENT.
PING_PROPERTIES = [
    (0x100007D8, 0x16, 1),                   # show on the map
    (0x1000009C, 0x10, TEAM_NUMBER),         # PVP_Team
    # Map note creation (0x64b150, 2026-10-05 night) reads icon 0x10000083 (DID,
    # 0x156470) and category 0x100004da (u32, 0x113a90) from the ENTITY'S OWN
    # properties, and the entity listener 0x680cd0 re-reads the icon on change;
    # whether the twin record's defaults are merged into the entity is unknown,
    # so the icon is sent explicitly (twin 0x49000a9c: icon 0x13000a15, category
    # 0x12). Category kind not verified yet (check with propdef.py). EXPERIMENT.
    (0x10000083, 0x15, 0x13000A15),          # map note icon (green "running men")
    # VERIFIED 23:10 2026-10-05: with the icon sent, the minimap shows the green
    # running-men note. propdef (in-world): 0x100004da kind 8 (enum), 0x10000909
    # kind 0x16 (bool, referenced only by the ping's scriptlet 0x3400053c ->
    # candidate "UseVFX" switch for the ground marker). EXPERIMENT.
    (0x100004DA, 8, 0x12),                   # map note category (twin value)
    (0x10000909, 0x16, 1),                   # scriptlet-only bool on the ping
    # 0x10000b96 / 0x10000b97 / 0x10000029 / 0x10000155 = true turned the arrows
    # YELLOW (the "alert" variant) and still showed no ground marker (2026-10-05);
    # the video's arrows are green, so they are left out.
]


def ping_object_id(step):
    return PING_OBJECT_ID + step


def build_ping(step):
    """The guide ping entity for a step (a NEW object per step: teleporting the
    same ping with an update bundle made the arrows vanish, 2026-10-05); None
    when the step has no target."""
    xyz = TUTORIAL_TARGETS.get(step)
    if not xyz:
        return None
    pos = (1, 0x13, 0xCB, 0) + xyz
    return build_create_object(ping_object_id(step), class_id=PING_CLASS, position=pos, sequence=1,
                               tele_seq=1, properties=PING_PROPERTIES)


def build_remove_object(object_id):
    """Event 0x3 addressed to the object = remove it (serializer 0x70d380: u8 base
    only; objmgr 0x24e070 -> 0x24dde0 hides it at once and frees it 30 s later).
    Re-sending a bundle for the id within those 30 s resurrects it."""
    return build_message(object_id, 0x3, bytes(1))


# Player pings (Alt+click / G): client event 0x2136 to service ...0008 =
# f32 x | f32 y (landblock-local, seen (27.9, 64.4) in lb 13cb) | u64 target
# IID (0 = ground) | u32 ping type (1 and 2 seen). A real server answers by
# creating a "Map Ping" entity for the team; the plain ping records 0x4000025a /
# 0x4000025b (pack 0xa00000b3) carry the icon 0x13000a15 but no scriptlets (the
# guide ping 0x40000a9c has the arrow scriptlets). EXPERIMENT 2026-10-05 night:
# one object per ping, removed again after PLAYER_PING_LIFETIME seconds.
PLAYER_PING_CLASSES = {1: 0x4000025A, 2: 0x4000025B}
PLAYER_PING_LIFETIME = 6.0
PLAYER_PING_BASE_ID = 0x0200000000000040
PLAYER_PING = {"count": 0}


def answer_ping(body):
    x, y, target, ptype = struct.unpack_from("<ffQI", body, 0)
    PLAYER_PING["count"] += 1
    object_id = PLAYER_PING_BASE_ID + (PLAYER_PING["count"] % 0x20)
    class_id = PLAYER_PING_CLASSES.get(ptype, 0x4000025A)
    spawn = current_spawn()
    pos = (spawn[0], spawn[1], spawn[2], 0, x, y, spawn[6])
    log_line(f"    ping request type {ptype} at ({x:.1f}, {y:.1f}) target {target:#x} -> object {object_id:#x} class {class_id:#x}")
    threading.Timer(PLAYER_PING_LIFETIME, lambda: send_user(build_remove_object(object_id))).start()
    return [(f"player ping object (class {class_id:#x})",
             build_create_object(object_id, class_id=class_id, position=pos, sequence=1, tele_seq=1,
                                 properties=PING_PROPERTIES))]




def at_tutorial_target():
    xyz = TUTORIAL_TARGETS.get(TUTORIAL["step"])
    if not xyz:
        return True
    px, py, _ = MOVER["pos"]
    return math.hypot(px - xyz[0], py - xyz[1]) <= TARGET_RADIUS


TUTORIAL_MOVE_STEPS = {
    1: ((0x193, 0x19c), "<font color='#FFFF00'>Right-click</font> to move to the marked location", HINT_GUIDE_ARROWS),
    2: ((0x1ac, 0x1b8), "<font color='#FFFF00'>Right-click</font> the drone to <font color='#00FF00'>Basic Attack</font> and defeat it", HINT_BASIC_ATTACK),
}


def tutorial_arrived():
    """The champion reached a move target: play the step's conversations and
    replace the objective text (0x2009 can only update an existing objective)."""
    step = TUTORIAL_MOVE_STEPS.get(TUTORIAL["step"])
    if not step:
        return []
    TUTORIAL["step"] += 1
    keys, text, hint = step
    msgs = [("previous guide ping removed (0x3)", build_remove_object(ping_object_id(TUTORIAL["step"] - 1)))]
    ping = build_ping(TUTORIAL["step"])
    if ping:
        msgs.append(("guide ping for the next target (object bundle)", ping))
    msgs += conversations(*keys)
    if hint:
        msgs.append((f"tutorial hint {hint} (0x2 / 0x1000027f)", build_tutorial_hint(hint)))
    if text:
        TUTORIAL_OBJECTIVE_TEXTS[1] = text
        msgs.append(("objective 1 new text (0x2009)", build_objective_update(tutorial_objective(1, True))))
    return msgs


def build_vitals(object_id, vitals):
    """0x42 to an entity that has a vitals component (i.e. created from a
    champion variant; a bare world state has none and the client crashes):
    u8 base | compact n + n x (cur, max) | compact n + n x (cur, max) |
    compact n + change records (none) | u8. Values are packed 15-bit ints
    (rva 0x56d3f0). The first list goes to component+0x18, the second to
    component+0x50, which is what the HUD query InqVital reads; index 0 =
    health, 1 = the champion's secondary vital."""
    pairs = b"".join(struct.pack("<HH", int(cur) & 0x7FFF, int(mx) & 0x7FFF) for cur, mx in vitals)
    # The HUD shows list 1 + list 2 (both filled doubled the numbers), so the
    # first list (bonus / temporary part) is sent as zeros.
    zeros = bytes(len(pairs))
    body = bytes([0, len(vitals)]) + zeros + bytes([len(vitals)]) + pairs + bytes([0, 0])
    return build_message(object_id, 0x42, body)


CHAMPION_VITALS = [(600, 600), (100, 100)]   # health, secondary (placeholder numbers)
TUTORIAL = {"step": 0}


def tutorial_start():
    """Intro cinematic finished: reveal the HUD and give the first objective."""
    if TUTORIAL["step"]:
        return []
    TUTORIAL["step"] = 1
    # Right after the cinematic the client's property reads on the player
    # object fail for ~2 s (tracer: 0x113a90(player, 0x956) returns 0 until the
    # next periodic object resend arrives) -> dark default lighting until then.
    # Re-sending the objects at once closes that gap (EXPERIMENT 2026-10-05).
    if QUEUE_STATE.get("avatar_seq"):
        QUEUE_STATE["avatar_seq"] += 1
        send_user(build_match_objects(sequence=QUEUE_STATE["avatar_seq"]))
    msgs = [(f"HUD element {e} restored (0x213d)", build_hud_element(e, HUD_EVENT_FIRST_RESTORED))
            for e in TUTORIAL_START_ELEMENTS]
    msgs.append(("champion vitals (0x42)", build_vitals(CHAMPION_AGENT_ID, CHAMPION_VITALS)))
    msgs.append(("objective list (0x2034)", tutorial_objectives()))
    # [00:33] "Ok, you're connected." / "Quickly, move Gaslight Batman to safety!"
    msgs += conversations(0x1ba)
    msgs.append(("guide ping (object bundle)", build_ping(1)))
    # 0x2075 (serializer rva 0x439720: u8 base | u8 enabled; handler 0x614010)
    # switches the objective tracker on (GM_Encounter.RecvNotice_UI_
    # SetObjectiveTrackerEnabled). Delivering the list resets the switch to off
    # and the script ignores an "on" that arrives while it is still closing,
    # so the enable is sent a little later.
    # EXPERIMENT (2026-10-05): the cinematic report now arrives only ~2 s after
    # the HUD is shown (was ~7 s on 2026-10-01) and the objective tracker never
    # appears, so the whole batch is held back until the HUD has settled.
    def deliver():
        for label, msg in msgs:
            log_line(f"--- sent {len(msg)} bytes ({label})")
            send_user(msg)
        if TUTORIAL_SHOW_TRACKER:
            threading.Timer(2.0, lambda: send_user(build_message(LOCAL_PLAYER_ID, 0x2075, bytes([0, 1])))).start()
    threading.Timer(TUTORIAL_START_DELAY, deliver).start()
    return []


TUTORIAL_START_DELAY = 0.5
# The real tutorial shows its objective only as the top-centre banner (reference
# video); the right-side tracker (enabled with 0x2075) stays closed.
TUTORIAL_SHOW_TRACKER = False
# The real tutorial (reference video) starts with only the portrait, the
# minimap and the objective banner; vitals, skills bar and skill buttons
# (elements 2, 14, 6, 9, 17, 25, 12, 7, 20, 31) are revealed in later steps.
TUTORIAL_START_ELEMENTS = (HUD_PORTRAIT, HUD_MINIMAP, HUD_MISSION_OBJECTIVES, 32)   # 32 = HintManager


def build_initial_events():
    # Set local player (serializer rva 0x453c0): u8 base | u64 player id |
    # property table (rva 0x109950: u8 table size class | compact count | ...).
    # Sets the "local player id" global (rva 0x176a710); without it the object
    # manager parks every object-creation event (0xF2).
    set_player = b"\x00" + struct.pack("<Q", LOCAL_PLAYER_ID) + b"\x00" + pack_compact(0)
    # Character list (serializer rva 0x449630): u8 base | u8 table size class
    # (<23) | compact count | entries (reader rva 0x446aa0 / 0x477cf0):
    #   u32 champion id | u32 a | u32 b | u32 c | u64 d | u64 e
    # The handler (rva 0x67e4b0) stores the table and the UI notifier (rva
    # 0x633090) forwards it to script as GM_UI.RecvNotice_CharacterAdvancementData
    # (ids, a, b, c, lo32 d, lo32 e) -- but ONLY IF THE TABLE IS NOT EMPTY.
    # Champion ids are CHARACTER VARIANT DIDs (prefix 0x40, one per heavy pack;
    # champions.json "variant"). Each also has a pregame-light record (prefix
    # 0x48, "id"), see champions.json (tools/champions.py, heavy_packs.py).
    # Fields (from the script handler RecvNotice_CharacterAdvancementData):
    #   did | level | current XP | next-level XP | u64 last used (unix s) | u64 ranked last used
    champions = [(c["variant"], 1, 0, 100, 0, 0) for c in ROSTER]
    char_list = (b"\x00" + b"\x00" + pack_compact(len(champions))
                 + b"".join(struct.pack("<IIIIQQ", *c) for c in champions))
    # The loading screen's checklist is a bitmask at [login flow (global rva
    # 0x17763c0) + 0x6c]: 1 = connected, 2 = champions, 4 = encounters, 8 = ?
    # (setters rva 0x69b170 / 0x69b1c0 / 0x69b210 / 0x69b260).
    #
    # Bit 2: event 0x20ED (serializer rva 0x43bcf0, handler rva 0x6833d0):
    #   u8 base | u32 count, each = (u32 count, each = 20-byte item rva 0x477c10)
    #   | table (u8 size class | compact count | entries rva 0x476750).
    # This is the champion roster grouped as [base champion, variant, ...]
    # (lookup rva 0x45df40: id == first item of a group -> base, else variant).
    # Item on the wire (17 bytes): u32 champion id | u32 | u32 | u8 bool | u32.
    # The outer array must NOT be empty (else the client re-requests once,
    # then errors) and NO GROUP may be empty (the landing screen dereferences
    # each group's first item -> crash). EXPERIMENT: one group per champion =
    # [champion, its costumes...]. Items are "ownables":
    #   u32 did | u32 content status | u32 content type | u8 owned | u32 count
    # (script enums: status 1 Free, 2 Available, 3 Disabled, 4 Unreleased,
    #  5 Hidden, 6 AlwaysOwned; type 1 Character, 4 Skins, 5 Amplifier, ...).
    def ownable(did, content_type, status=2, owned=1):
        return struct.pack("<IIIBI", did, status, content_type, owned, 1)
    groups = b""
    all_items = b""
    n_items = 0
    # Do NOT add more light packs to a group than fit: the pack manager has a
    # fixed number of slots per pack category (allocator rva 0x5d3400; light
    # packs = category 6, 16 slots). A pack that gets no slot is skipped
    # silently, its heavy load never completes, and every later champion click
    # queues forever (blank detail view). Tried with all 43 light packs.
    for c in ROSTER:
        # Last member: a HIDDEN, NOT OWNED pseudo-variant (script
        # OwnablesManager.CalculateOwnableUIState: Hidden + not owned ->
        # OWNABLE_UI_STATE_UNLISTED, skipped by the costume row; Hidden + owned
        # -> OWNED, which showed as an empty costume slot) whose metadata light pack is the
        # champion's "skills UI" pack (skill icons + skill-name string table,
        # champions.json skills_pack). LoadCharactersHeavy (rva 0x656410 /
        # 0x63e240) loads the light pack (+0x0c) of every group member, which is
        # the only way to get that pack loaded in the profile view.
        members = ([ownable(c["variant"], 1)] + [ownable(s["variant"], 4) for s in c["costume_info"]]
                   + [ownable(c["skills_key"], 4, status=5, owned=0)])
        all_items += b"".join(members)
        n_items += len(members)
        groups += struct.pack("<I", len(members)) + b"".join(members)
    # Event 0x20b8 (handler rva 0x688030): the account's item statuses ->
    # GM_UI.RecvNotice_ItemStatuses + RecvNotice_AvailableCharacterList (rva
    # 0x67b2f0, once the 0x20ED data has also arrived). The Champions tab needs
    # these plus the advancement data above.
    item_statuses = bytes([0]) + struct.pack("<I", n_items) + all_items
    # Trailing table = per-champion metadata the UI reads natively (rva 0x625510
    # icon, 0x625580 name). Entry (readers rva 0x476750 / 0x466240):
    #   u32 champion did | 8 x u32 (unknown) | u8 bool | u32 char-picker icon
    #   | StringInfo name
    # StringInfo (rva 0x1a9580): u8 mode; mode 1 = literal wstring (compact
    # length + UTF-16), else u32 + u32 (table/token); then a variables table
    # (u8 size class | compact count).
    # EXPERIMENT: icon = the champion record's texture property 0x10000384;
    # the other texture (0x10000799) goes in the first unknown slot.
    def wstring(text):
        return pack_compact(len(text)) + text.encode("utf-16le")
    # Metadata value layout (offsets into the client's entry; getters by rva):
    #   +0x00 u32 ?            +0x04 parent pack (0x466480; e.g. shared powerset pack)
    #   +0x08 HEAVY pack (0x466540)   +0x0c LIGHT pack (0x4664e0)   (-1 = none;
    #         a 0 here is requested as "pack 0", never completes, and blocks every
    #         later character load -> blank champion detail view)
    #   +0x10 u32 ?            +0x14 heavy DBPC did (0x6254a0)
    #   +0x18 light DBPC did = pregame-light record (0x625430)
    #   +0x1c powerset DBPC did (0x4665a0)   +0x20 bool   +0x24 char-picker icon
    #   +0x28 StringInfo name
    # (script: RecvNotice_ProfileUI_HeavyResourcePackData(didCharacter,
    #  didHeavyDBPC, didPowerSetDBPC, didLightDBPC)).
    NONE = 0xFFFFFFFF
    def meta_entry(variant, parent_pack, heavy_pack, light_pack, wallpaper_pack, heavy_dbpc, light_dbpc,
                   powerset_dbpc, icon, name):
        return (struct.pack("<I", variant)
                # +0x00 and +0x10 are pack ids too (the client's blank entry
                # initialises +0..+0x10 to -1; +0x10 is read by rva 0x6253b0
                # and loaded with the heavy set), so they must be -1, not 0.
                # +0x10 is loaded together with the heavy pack by LoadCharactersHeavy
                # (list = [+0x08, +0x10, variants' packs...]); a -1 there leaves
                # the load pending forever. EXPERIMENT: +0x10 = the "pregame
                # heavy" pack (one 0x48 record + the wallpaper texture, usually
                # light pack id - 1) and +0x14 = that 0x48 record, which the
                # script reads Character_WallpaperImage_Property (0x100005b0) from.
                + struct.pack("<8I", NONE, parent_pack, heavy_pack, light_pack, wallpaper_pack,
                              heavy_dbpc, light_dbpc, powerset_dbpc)
                + bytes([1]) + struct.pack("<I", icon)
                + bytes([1]) + wstring(name) + bytes([0]) + pack_compact(0))
    # Powerset DBPC (+0x1c) = the variant's 0x49 heavy record (in the heavy pack,
    # which the profile view loads). GM_Skill.SendQuery_InqSkillToolTipInfo
    # (native worker rva 0x66de10) resolves it and reads the skill-slot struct
    # properties from it (slot -> property table rva 0x11eda28: slot 1..5 =
    # 0x100008e8 / 8ea / 8ec / 8e6 / 8ef). The old guess (a 0x49 record in the
    # parent pack) is never resident in menus, so the query bailed silently.
    meta = b""
    n_meta = 0
    for c in ROSTER:
        meta += meta_entry(c["variant"], c["parent_pack"], c["heavy_pack"], c["light_pack"], c["wallpaper_pack"],
                           # icon (+0x24, script CharacterData.didPregameIcon, used by
                           # the Champions grid): heavy-record property 0x1000072e, a
                           # texture in the always-loaded pack 0xa0000103. (The 0x10000384
                           # portrait lives in the light pack, and only 16 light packs fit:
                           # pack category 6 has 16 slots, allocator rva 0x5d3400.)
                           c["pregame_heavy"], c["id"], c["heavy_dbpc"], c["grid_icon"], c["name"])
        n_meta += 1
        for s in c["costume_info"]:
            meta += meta_entry(s["variant"], c["parent_pack"], s["heavy_pack"], s["light_pack"], s["wallpaper_pack"],
                               s["pregame_heavy"], s["light"], s["heavy_dbpc"], 0, c["name"])
            n_meta += 1
        meta += meta_entry(c["skills_key"], NONE, NONE, c["skills_pack"], NONE,
                           0, 0, 0, 0, c["name"])
        n_meta += 1
    champ_data = (bytes([0]) + struct.pack("<I", len(ROSTER)) + groups
                  + bytes([0]) + pack_compact(n_meta) + meta)
    # Bit 4: event 0x2024 = gmCEncounterManagementSystem::RecvEvt_DeliverEncounterInfo
    # (serializer rva 0x446d40, handler rva 0x6733b0):
    #   u8 base | u32-counted array x2 | u32-counted array | u32-counted array
    #   | u32 | u32-counted array | u8 bool | wstring | wstring | u64
    # (wstring = compact length + UTF-16 chars). Array elements are u32 ids.
    # EXPERIMENT: the first array (encounter ids) must be non-empty for the
    # landing-screen gate below; id 1 is a placeholder.
    # The four leading arrays are PARALLEL (one entry per encounter): ids,
    # u32s, narrow strings (compact length + bytes; a delimited tag list
    # matched against the trailing string array, rva 0x46fd90), u32s. Giving
    # them different lengths crashes the client (rva 0x613ef0 indexes them all
    # by the first array's count).
    # Encounter ids = 0x40 DIDs (twin 0x49 record holds name 0x10000047 etc.)
    # from the master encounter list in pack 0xa00000b3 (offset 0x47668: pairs
    # of (did, 0x100001d3)); "[e]" test/dev entries left out.
    n = len(ENCOUNTERS)
    encounters = (b"\x00"
                  + struct.pack("<I", n) + b"".join(struct.pack("<I", e) for e, _ in ENCOUNTERS)  # ids
                  # per-encounter flags (RecvQuery_InqPVPEncounters rva 0x668211..):
                  # bit 21, bit 17, bit 16 -> three per-encounter bool outputs, most
                  # likely BlindPick / Draft / Ranked support; with none set the
                  # script (EncounterDataObject.IsNoQueuesAvailable) shows "Queues
                  # are currently unavailable". EXPERIMENT: bits 21+17, not tutorials.
                  + struct.pack("<I", n) + b"".join(
                      struct.pack("<I", 0 if "Tutorial" in name else (1 << 21) | (1 << 17))
                      for _, name in ENCOUNTERS)
                  + struct.pack("<I", n) + b"\x00" * n                 # per-encounter tag string (empty)
                  + struct.pack("<I", n) + b"\x00\x00\x00\x00" * n     # per-encounter u32
                  + struct.pack("<I", 0)
                  + struct.pack("<I", 0) + b"\x00" + pack_compact(0) + pack_compact(0)
                  + struct.pack("<Q", 0))
    # Second table of 0x218B = game settings, name -> typed value (reader rva
    # 0x448120 / 0x447650: key = compact length + bytes, value = compact type id
    # + data). Read by name through rva 0x46b5b0 ("FeaturedMap_PVP" /
    # "FeaturedMap_BOTS" in RecvQuery_InqPVPEncounters 0x668030,
    # "FeaturedMap_RANKED", "Client_Trainee_AchievementList", ...); string values
    # go through strtoul(s, 0, 0). Type id 9 = string kind (live type registry
    # at rva 0x1766cb4; its kind field (+0xc) = 1 = string object, which the
    # featured-map code converts with ToString).
    # Wire: type id = 2 bytes BIG-endian (reader rva 0xfc420; first byte 0x80 ->
    # u32 follows, 0xC0 -> 4-byte form, bit 0x40 -> 0x10000000 | low 14 bits);
    # kind-1 string data = u32 length + bytes (rva 0xfeac0). (A compact type id
    # + compact length made the client reject the whole 0x218B event.)
    def setting(name, value):
        return (pack_compact(len(name)) + name.encode() + struct.pack(">H", 9)
                + struct.pack("<I", len(value)) + value.encode())
    settings = [setting("FeaturedMap_PVP", "0x40000399"),     # Gotham Divided
                setting("FeaturedMap_BOTS", "0x40000B6A")]    # Coast City v AI
    game_settings = b"\x00" + pack_compact(len(settings)) + b"".join(settings)
    # EXPERIMENT (2026-10-01 15:25): the placeholder player object (entity
    # 0x2D000002) never becomes "ready" in the menus; entering a match first
    # clears the world (rva 0x342120), and releasing that half-built entity hits
    # a pure-virtual call (fatal 0xFFFFFF via 0x6ee8f0). Try logging in without it.
    player_object = ([("create local player object",
                       build_create_object(LOCAL_PLAYER_ID, class_id=PLAYER_ENTITY_DID))]
                     if CREATE_PLAYER_OBJECT else [])
    return [
        ("set local player -> player system",
         build_message(SVC_PLAYER_SYSTEM, EVT_SET_LOCAL_PLAYER, set_player)),
        # The login flow keeps a second "pending" mask at [flow+0x68]; bit 2
        # only clears once the local player object exists (rva 0x699140 / 0x2351d0).
        *player_object,
        ("item statuses (0x20b8) -> player system",
         build_message(SVC_PLAYER_SYSTEM, 0x20B8, item_statuses)),
        ("champion data (bit 2) -> player system",
         build_message(SVC_PLAYER_SYSTEM, EVT_CHAMPION_DATA, champ_data)),
        # ORDER MATTERS (script OwnablesManager.CheckHasAllData): item statuses and
        # the available-character list (0x20b8 + 0x20ED) must reach the UI BEFORE
        # the advancement data (0x209D), otherwise the script marks its data
        # complete without ever building its champion table (empty Champions tab).
        ("char list -> player system",
         build_message(SVC_PLAYER_SYSTEM, EVT_MASTER_CHARACTER_LIST, char_list)),
        ("encounter info (bit 4) -> player system",
         build_message(SVC_PLAYER_SYSTEM, EVT_DELIVER_ENCOUNTER_INFO, encounters)),
        # --- Landing-screen gate (rva 0x670db0): the client only sends
        # GM_UI.RecvNotice_ProtectorAdvancementStatus to the UI (whose handler
        # loads the landing screen) once ALL of these hold:
        #   encounter list non-empty; achievements received (0x2120);
        #   charsys+0x8c != 0 (0x2080); charsys+0x88 set (0x218b);
        #   server options received (0x216a); charsys+0x48 "status" != 0
        #   (source of the status value not found yet).
        ("server options (0x216a)",    # handler rva 0x6742d0: table name -> typed value
         build_message(SVC_PLAYER_SYSTEM, 0x216A, EMPTY_TABLE_EVENT)),
        ("achievements (0x2120)",      # gmCAchievementSystem::SetAllAchievements, rva 0x6839e0
         build_message(SVC_PLAYER_SYSTEM, 0x2120, EMPTY_TABLE_EVENT + struct.pack("<I", 0))),
        ("account tables (0x218b)",    # handler rva 0x6839b0: two tables -> charsys+0x60
         build_message(SVC_PLAYER_SYSTEM, 0x218B, EMPTY_TABLE_EVENT + game_settings)),
        ("account flags (0x215d)",     # handler rva 0x676b80: u32 -> charsys+0x40, bool -> +0x45
         build_message(SVC_PLAYER_SYSTEM, 0x215D, b"\x00" + struct.pack("<I", 1) + b"\x00")),
        # Bit 8: event 0xCE (serializer rva 0x45310, handler rva 0x298920 ->
        # 0x2a8520 -> notice 0x12 -> account object rva 0x4241d0 -> notice 0x31
        # -> login flow rva 0x69be40):
        #   u8 base | u32 count, each = 0x48-byte entry (rva 0x216f0: u64 id,
        #   two property tables, ...; looks like the account's character list)
        #   | property table (u8 size class | compact count).
        # With entries the client reads the first one's id/name and acts on it
        # (rva 0x48a860); with none it just sets bit 8. EXPERIMENT: empty.
        ("account/character set (bit 8) -> player system",
         build_message(SVC_PLAYER_SYSTEM, EVT_ACCOUNT_CHARACTER_SET, build_character_set())),
        # Sent LAST on purpose: this is the event that makes the landing gate
        # pass, which posts UI state event 0x6f (DeliveredProtectorAdvancementStatus,
        # rva 0x6c5af0) into the UI state machine. That must happen AFTER
        # Connection_Connected (0x22), i.e. after the checklist completes.
        ("account level/xp (0x2080)",  # handler rva 0x67dfb0: 6 x u32, 2 x f32; first u32 != 0
         build_message(SVC_PLAYER_SYSTEM, 0x2080,
                       # First u32 = account level. With no stored status the
                       # client derives it (rva 0x670e7e): level 1 + no trainee
                       # achievement = new player (3), level < 5 = trainee (2),
                       # else veteran (1). Only veteran skips the trainee
                       # light-pack load, so use a veteran level.
                       b"\x00" + struct.pack("<6I2f", ACCOUNT_LEVEL, ACCOUNT_LEVEL, 0, 100, 0, 0, 0.0, 0.0))),
    ]


def build_frame(packets_mask, payload, header=0x01):
    """Frame format (client receive path rva 0x70b6c0 -> frame parser 0x70af10):
      u32 len | u8 header | [header&1: u32 packet bitmask, then each packet's
      fields in ascending bit order]. header & 0xF0 selects the frame filter
      (decrypt/decompress) installed on the connection."""
    frame = bytes([header]) + struct.pack("<I", packets_mask) + payload
    return struct.pack("<I", len(frame)) + frame


def build_hello_reply(hello):
    """EXPERIMENT: answer the client hello with a 0x40000 "welcome" packet
    (builder rva 0x705070, handler rva 0xbe4950):
      +0  16 bytes  session/route id
      +16 8 bytes   server time, big-endian double (synced into client clock)
      +24 8 bytes   ?
      +32 u32       ?
      +36 u32 BE    low byte -> connection id high part (0x07000200 | b<<16)
      +40 u32 BE    connection id low part
    """
    now = datetime.datetime.now().timestamp()
    pkt = (bytes(16) + struct.pack(">d", now) + bytes(8)
           + struct.pack("<I", 0) + struct.pack(">II", 1, 1))
    return build_frame(0x00040000, pkt)


def build_referral(host, port, cookie=1):
    """EXPERIMENT: packet 0x800 = Referral (builder rva 0x70831a, body reader
    0x704be0, handler EngineClientNet slot +0x9c = 0x2a8890 -> 0xbe3bd0 ->
    0xbe3240, which resolves host:port and opens a new connection; a failed
    resolve posts connection notice 6):
      u64 recipient id/cookie | u16 | u8 flags (bit 8 -> EngineClientNet+0x3c0,
      bit 1 checked vs +0x1c5) | u8 | u16 port (no byte swap) | char[256] host"""
    pkt = (struct.pack("<QHBBH", cookie, 0, 0, 0, port)
           + host.encode().ljust(256, b"\x00"))
    return build_frame(0x00000800, pkt)


TUTORIAL_CHAMPION = 0x40000086   # Gaslight Batman (Tutorial 1 in old gameplay videos)
TUTORIAL_AVATAR = 0x2E0001B2     # his world state (heavy pack 0xa0000076, parent entity 0x2D000115)
# EXPERIMENT: the player object itself = generic player world state (pack
# 0xa0000037, parent entity 0x2D000002) instead of a second, gliding Batman.
# If the match load stalls, set it back to TUTORIAL_AVATAR.
PLAYER_AVATAR = 0x40000086
# ^ EXPERIMENT 2026-10-05 (darkness): the player object is now ALSO built from the
# champion variant record, so that it gets the game components. The fog-of-war
# component (vtable 0x12098e8) only activates on the entity that is the local
# player (rva 0x6add80) and reveals around the entity named by that entity's
# property 0x100000cf (= our agent). After the intro cinematic 0x35000026 ends
# the client switches fog of war on; with no active component everything stays
# fogged = the "dark world". Before: TUTORIAL_AVATAR (bare world state 0x2E0001B2;
# 0x2E000003 could not be placed at all).
ROOM_ID = 1
# Packs the match needs (0x20AF second list): Gaslight Batman's heavy pack so his
# avatar world state 0x2E0001B2 can be built (WEF failed "wstate load" without it).
MATCH_PACKS = [0xA0000076]


def build_enter_match():
    """EXPERIMENT: event 0x20AF (serializer rva 0x4452d0, execute 0x4ac0e0,
    handler 0x699f00 = gmConnectionManager):
      u8 base | u32 (-> flow+0x74) | u32 n + DIDs (-> flow+0xa4: characters whose
      parent packs LoadParentRPs 0x699370 loads, via metadata +0x04) | u32 n + DIDs
      (-> +0xb4) | u32 DID (-> +0xc4: record read for properties 0x1000028a /
      0x10000406 by 0x699e20)
    Sets lobby+0x4cb, flow+0x70 bit 2 (and bit 4 unless lobby +0x4ca/+0x4c8),
    then 0x699e20 loads match data + parent packs once bits 1|2|4 are set."""
    did = QUEUE_STATE.get("encounter", (0x40000991, 0))[0]
    packs = MATCH_PACKS   # second list = raw pack ids for LoadMatchData_ (0x699460)
    body = (b"\x00" + struct.pack("<I", 0)
            + struct.pack("<II", 1, TUTORIAL_CHAMPION)
            + struct.pack("<I", len(packs)) + b"".join(struct.pack("<I", p) for p in packs)
            + struct.pack("<I", did))
    return build_message(SVC_PLAYER_SYSTEM, 0x20AF, body)


def build_lobby_state():
    """EXPERIMENT: event 0x204C = lobby state / encounter details (serializer rva
    0x445810, execute 0x4b8970, handler 0x6bde80):
      u8 base | u32 (lobby+0xac) | u32 (+0xb0) | u32 encounter did | u32 queue flags
      (bit 17 -> room +0x240 = -1) | u64 | u32 (+0xbc) | u32 ROOM ID (lobby+0x4bc)
      | u32 n + ownables[17: u32 did, u32 status, u32 type, u8 owned, u32 count]
      (available champions) | u32 n + DIDs (lobby+0x30, used by
      VerifyAndLoadAllNeededRPS) | u8 | u8"""
    did, qflags = QUEUE_STATE.get("encounter", (0x40000991, 0))
    owned = struct.pack("<IIIBI", TUTORIAL_CHAMPION, 2, 1, 1, 1)
    return (b"\x00" + struct.pack("<II", 0, 0) + struct.pack("<II", did, qflags)
            + struct.pack("<QII", 0, 0, ROOM_ID)
            + struct.pack("<I", 1) + owned
            + struct.pack("<II", 1, TUTORIAL_CHAMPION)
            + b"\x00\x00")


def game_server_client(conn, addr):
    log_line(f"\n===== {datetime.datetime.now().isoformat()} GAME SERVER connect from {addr}")
    first = True
    # EXPERIMENT: the client closed the game connection ~5 s after connecting
    # while the server stayed silent (-> connection-closed 0xbe2270 -> event
    # 0x1006 -> notice 0x15 -> ID_ConnectionError_EndCharacterSession). Keep it
    # alive with the same time packet the client sends us on the login link
    # (frame header 0x01, packet bit 0x01000000, big-endian double time;
    # handled by the base packet dispatcher 0x703cc0).
    conn.settimeout(2.0)
    with conn:
        while True:
            try:
                data = conn.recv(65536)
            except socket.timeout:
                if not first:
                    conn.sendall(build_frame(0x01000000, struct.pack(">d", datetime.datetime.now().timestamp())))
                    # EXPERIMENT: stream the avatar's position like a live server
                    # would (the client's physics motion queue, rva 0x209c70,
                    # interpolates time-stamped samples; one sample never applied).
                    user = QUEUE_STATE.get("user_conn")
                    if user is not None and QUEUE_STATE.get("avatar_seq"):
                        QUEUE_STATE["avatar_seq"] += 1
                        # Live experiments: logs/send.txt lines "<dest: player|svc|hex> <event hex> <body hex>"
                        # are sent on the login connection.
                        sendf = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "send.txt")
                        if os.path.exists(sendf):
                            try:
                                lines = open(sendf).read().splitlines()
                                os.remove(sendf)
                                for ln in lines:
                                    if ln.strip():
                                        dest, ev, hx = ln.split(None, 2)
                                        dest = LOCAL_PLAYER_ID if dest == "player" else SVC_PLAYER_SYSTEM if dest == "svc" else int(dest, 16)
                                        user.sendall(build_message(dest, int(ev, 16), bytes.fromhex(hx)))
                                        log_line(f"--- sent (send.txt) {ev} {hx}")
                            except (OSError, ValueError) as e:
                                log_line(f"--- send.txt failed: {e}")
                        if False and QUEUE_STATE["avatar_seq"] == 3 and CINEMATIC_DID:   # now sent at load complete
                            # EXPERIMENT: event 0x20F5 (serializer 0x43bdb0 -> struct
                            # 0x478020: u32 flags | [bit10 u32] | [bit0 u32 DID of a
                            # type-0x3e (prefix 0x35) camera/cinematic record] | ...;
                            # handler 0x69d140 -> 0x69cff0 -> camera director
                            # 0x2a6540 loads it; when loaded (state 3, 0x2a5f20) the
                            # camera gets the LOCAL PLAYER as target -> SmartBox
                            # viewer valid -> world renders.
                            cin = b"\x00" + struct.pack("<II", 0x1, CINEMATIC_DID)
                            try:
                                send_user(build_message(LOCAL_PLAYER_ID, 0x20F5, cin))   # needs an entity recipient (QI 0x11a7a70)
                                log_line(f"--- sent camera/cinematic 0x20f5 did {CINEMATIC_DID:#x}")
                            except OSError:
                                pass
                        try:
                            send_user(build_match_objects(sequence=QUEUE_STATE["avatar_seq"]))
                        except OSError:
                            pass
                continue
            if not data:
                break
            log_line(f"--- {datetime.datetime.now().isoformat()} GAME recv {len(data)} bytes\n{hexdump(data)}")
            if not first:
                # The client's frames on this connection are plain only with the
                # exe patch at rva 0xbe4462 (no OodleNetwork1 TCP send filter).
                QUEUE_STATE["game_pending"] = handle_client_frames(
                    conn, QUEUE_STATE.get("game_pending", b"") + data)
            if first:
                first = False
                QUEUE_STATE["game_pending"] = b""
                reply = build_hello_reply(data)
                conn.sendall(reply)
                log_line(f"--- GAME sent {len(reply)} bytes (welcome/ConnectRequest)\n{hexdump(reply)}")
                # Packet 0x100 = ServerSwitch (builder rva 0x709bec: u32 sequence;
                # handler 0xbe2080 -> EngineClientNet slot +0x7c 0xbe2150 makes
                # this connection the CURRENT one, +0x1ac). Without it, once match
                # data has loaded the client closes every connection except the
                # current (login) one (0xbe33e0 -> 0xbe47f0, reason
                # ID_ConnectionError_EndCharacterSession) and the session ends.
                switch = build_frame(0x00000100, struct.pack("<I", 1))
                conn.sendall(switch)
                log_line(f"--- GAME sent {len(switch)} bytes (ServerSwitch 0x100)\n{hexdump(switch)}")
                # The ConnectRequest above gives gmConnectionManager +0x70 bit 1;
                # 0x20AF on the login connection gives bits 2 and 4 -> match load.
                user = QUEUE_STATE.get("user_conn")
                if user is not None:
                    msg = build_enter_match()
                    user.sendall(msg)
                    log_line(f"--- sent {len(msg)} bytes (enter match 0x20af)\n{hexdump(msg)}")
                    # 0x2016 "End Room Check" (serializer rva 0x439500: u8 base | u32
                    # room id; handler 0x6b9080): room id must equal lobby+0x4bc (0
                    # here) -> sets lobby+0xa8 "SetLobbyTransitionCalled" ->
                    # CheckTransitionToWorldLoad 0x6b8ec0 -> UI state event 0x23.
                    msg = build_message(SVC_PLAYER_SYSTEM, 0x2016, b"\x00" + struct.pack("<I", 0))
                    user.sendall(msg)
                    log_line(f"--- sent {len(msg)} bytes (end room check 0x2016)\n{hexdump(msg)}")
    log_line(f"===== GAME SERVER disconnect {addr}")


def run_game_server():
    threading.Thread(target=mover_thread, daemon=True).start()
    srv = socket.create_server((HOST, GAME_SERVER_PORT))
    print(f"Game server (experimental) listening on {HOST}:{GAME_SERVER_PORT}")
    while True:
        conn, addr = srv.accept()
        threading.Thread(target=game_server_client, args=(conn, addr), daemon=True).start()


def run_user_server():
    srv = socket.create_server((HOST, USER_SERVER_PORT))
    print(f"User server (capture only) listening on {HOST}:{USER_SERVER_PORT}")
    while True:
        conn, addr = srv.accept()
        threading.Thread(target=user_server_client, args=(conn, addr), daemon=True).start()


def run_user_server_udp():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((HOST, USER_SERVER_PORT))
    print(f"User server (UDP capture only) listening on {HOST}:{USER_SERVER_PORT}")
    while True:
        data, addr = sock.recvfrom(65536)
        log_line(f"\n===== {datetime.datetime.now().isoformat()} USER SERVER UDP from {addr} "
                 f"{len(data)} bytes\n{hexdump(data)}")


if __name__ == "__main__":
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    threading.Thread(target=run_user_server, daemon=True).start()
    threading.Thread(target=run_user_server_udp, daemon=True).start()
    threading.Thread(target=run_game_server, daemon=True).start()
    print(f"Login server listening on http://{HOST}:{PORT}  (log: {LOG_PATH})")
    http.server.ThreadingHTTPServer((HOST, PORT), LoginHandler).serve_forever()
