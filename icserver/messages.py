"""Message builders. Byte layouts are ported 1:1 from the original
infinite-crisis-server (login_server.py); the only change is that every value
comes in as an argument instead of a global, so they can be tested and reused
per session. tests/test_compat.py checks them byte-for-byte against the old code.
"""
import struct

from .wire import (KIND_BOOL, KIND_DID, KIND_ENUM, KIND_IID, KIND_INT, KIND_STRING, KIND_F32,
                   build_batch, build_frame, build_message, build_position, facing_yaw,
                   pack_compact, property_table, string_info, wstring)

# ---- ids ---------------------------------------------------------------------
SVC_PLAYER_SYSTEM = 0x0600000000000403     # client player/character system (rva 0x2a8090)
LOCAL_PLAYER_ID = 0x0200000000000001       # top byte 2 = player object
CHAMPION_AGENT_ID = 0x0200000000000002     # the champion the player controls
PING_OBJECT_ID = 0x0200000000000030        # guide pings: + step
PLAYER_PING_BASE_ID = 0x0200000000000040   # player pings: + n % 0x20
MARKER_OBJECT_ID = 0x0200000000000060      # visible tutorial markers: + step

PROP_CONTROLLED_AGENT = 0x100000CF
PROP_PLAYER_ENTITY_LINK_2 = 0x100005E8

EVT_SET_LOCAL_PLAYER = 0xEB
EVT_ACCOUNT_CHARACTER_SET = 0xCE
EVT_MASTER_CHARACTER_LIST = 0x209D
EVT_DELIVER_ENCOUNTER_INFO = 0x2024
EVT_CHAMPION_DATA = 0x20ED

EMPTY_TABLE_EVENT = b"\x00" + b"\x00" + b"\x00"   # u8 base | empty table
NONE32 = 0xFFFFFFFF

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


# ---- connection-level packets ------------------------------------------------------

def hello_reply(now):
    """0x40000 welcome (builder rva 0x705070, handler 0xbe4950): 16-byte route
    id | BE f64 server time | 8 | u32 | BE u32 | BE u32 connection id."""
    pkt = (bytes(16) + struct.pack(">d", now) + bytes(8)
           + struct.pack("<I", 0) + struct.pack(">II", 1, 1))
    return build_frame(0x00040000, pkt)


def time_packet(now):
    """Packet 0x01000000: BE f64 time (keepalive; base dispatcher 0x703cc0)."""
    return build_frame(0x01000000, struct.pack(">d", now))


def server_switch(sequence=1):
    """Packet 0x100 ServerSwitch (handler 0xbe2080): makes the game connection
    the current one; without it the client drops it once match data loads."""
    return build_frame(0x00000100, struct.pack("<I", sequence))


def referral(host, port, cookie=1):
    """Packet 0x800 Referral (handler 0x2a8890 -> 0xbe3240): u64 cookie | u16 |
    u8 flags | u8 | u16 port | char[256] host."""
    pkt = struct.pack("<QHBBH", cookie, 0, 0, 0, port) + host.encode().ljust(256, b"\x00")
    return build_frame(0x00000800, pkt)


# ---- account / menus -------------------------------------------------------------

def character_set(player_name, player_id=LOCAL_PLAYER_ID):
    """0xCE account character set (serializer rva 0x45310), one entry."""
    empty_table = b"\x00" + pack_compact(0)
    entry = (struct.pack("<QQ", player_id, 0) + wstring(player_name)
             + struct.pack("<I", 0) + empty_table + empty_table)
    return b"\x00" + struct.pack("<I", 1) + entry + empty_table


def _ownable(did, content_type, status=2, owned=1):
    return struct.pack("<IIIBI", did, status, content_type, owned, 1)


# 2026-10-16 16:36 (tester: Robin, Arcane Supergirl and Star Sapphire missing
# in game). Their champions.json lists a costume whose variant is the
# champion's own variant: the client got the variant again as a costume item
# (content type 4) and a second meta entry, and lost the champion. Only those
# three champions have such costumes. [account] skip_base_costumes.
SKIP_BASE_COSTUMES = True


def costumes(c):
    """The champion's costumes, without the ones that repeat its own variant
    (or an earlier costume's) when SKIP_BASE_COSTUMES is on."""
    if not SKIP_BASE_COSTUMES:
        return list(c["costume_info"])
    seen, out = {c["variant"]}, []
    for s in c["costume_info"]:
        if s["variant"] not in seen:
            seen.add(s["variant"])
            out.append(s)
    return out


def _champion_items(c, locked=()):
    owned = 0 if c["variant"] in locked else 1
    return ([_ownable(c["variant"], 1, owned=owned)] + [_ownable(s["variant"], 4) for s in costumes(c)]
            + [_ownable(c["skills_key"], 4, status=5, owned=0)])


# Extra owned items for every 0x20B8 delivery: [(DID, content type)], set at
# server start (icserver/cosmetics.py: the Protector / avatar icons, type 3).
# Every delivery carries them: from the second one on the client only passes
# the changes to Flash.
EXTRA_OWNABLES = []


def _item_statuses_body(roster, locked=()):
    items = [i for c in roster for i in _champion_items(c, locked)]
    items += [_ownable(did, ctype) for did, ctype in EXTRA_OWNABLES]
    return bytes([0]) + struct.pack("<I", len(items)) + b"".join(items)


def set_local_player(player_id=None):
    """0xEB: u8 0 | u64 local player id | u8 0 | compact 0 (sent at login; again
    before each later match: the client's world teardown resets it to 0)."""
    pid = LOCAL_PLAYER_ID if player_id is None else player_id
    return build_message(SVC_PLAYER_SYSTEM, EVT_SET_LOCAL_PLAYER,
                         b"\x00" + struct.pack("<Q", pid) + b"\x00" + pack_compact(0))


def item_statuses(roster, locked=()):
    """0x20B8 item statuses again (handler 0xa88030: from the second delivery
    on, only the changed items go to Flash as Incremental_ItemStatuses).
    locked = champion variants sent as not owned."""
    return build_message(SVC_PLAYER_SYSTEM, 0x20B8, _item_statuses_body(roster, locked))


def item_fulfilled(key, item_did, text=""):
    """0x2095 ribbon "item fulfilled" (serializer 0x83f410, handler 0x8aaf60 ->
    0xa7ea00): u8 0 | u32 key | u32 item DID | StringInfo text. Shown at home by
    GM_Character.RecvNotice_Ribbon_ItemFulfilled."""
    return build_message(SVC_PLAYER_SYSTEM, 0x2095,
                         b"\x00" + struct.pack("<II", key, item_did) + string_info(text))


def _meta_entry(variant, parent_pack, heavy_pack, light_pack, wallpaper_pack, heavy_dbpc, light_dbpc,
                powerset_dbpc, icon, name):
    return (struct.pack("<I", variant)
            + struct.pack("<8I", NONE32, parent_pack, heavy_pack, light_pack, wallpaper_pack,
                          heavy_dbpc, light_dbpc, powerset_dbpc)
            + bytes([1]) + struct.pack("<I", icon)
            + bytes([1]) + wstring(name) + bytes([0]) + pack_compact(0))


def _setting(name, value):
    return (pack_compact(len(name)) + name.encode() + struct.pack(">H", 9)
            + struct.pack("<I", len(value)) + value.encode())


# 2026-10-18 16:54: encounters whose map data is not in the install (only their menu entry and icon):
# Crime Alley (Tutorial 3, v AI, the Clash maps), Apokolips Causeway, Metropolis Skyway
MISSING_MAP_ENCOUNTERS = (0x40000CA6, 0x40000C82, 0x40000E68, 0x40000E74, 0x40000EC0, 0x40000C28)


def initial_events(roster, account_level, player_name, hidden=()):
    """Everything the client needs between login and the landing screen.
    ORDER MATTERS (see the old server's comments): 0x20b8 + 0x20ED before
    0x209D, and 0x2080 last (it opens the landing-screen gate)."""
    set_player = b"\x00" + struct.pack("<Q", LOCAL_PLAYER_ID) + b"\x00" + pack_compact(0)
    champions = [(c["variant"], 1, 0, 100, 0, 0) for c in roster]
    item_statuses = _item_statuses_body(roster)
    char_list = (b"\x00" + b"\x00" + pack_compact(len(champions))
                 + b"".join(struct.pack("<IIIIQQ", *c) for c in champions))
    groups = b""
    for c in roster:
        members = _champion_items(c)
        groups += struct.pack("<I", len(members)) + b"".join(members)
    meta, n_meta = b"", 0
    for c in roster:
        meta += _meta_entry(c["variant"], c["parent_pack"], c["heavy_pack"], c["light_pack"], c["wallpaper_pack"],
                            c["pregame_heavy"], c["id"], c["heavy_dbpc"], c["grid_icon"], c["name"])
        n_meta += 1
        for s in costumes(c):
            meta += _meta_entry(s["variant"], c["parent_pack"], s["heavy_pack"], s["light_pack"],
                                s["wallpaper_pack"], s["pregame_heavy"], s["light"], s["heavy_dbpc"], 0, c["name"])
            n_meta += 1
        meta += _meta_entry(c["skills_key"], NONE32, NONE32, c["skills_pack"], NONE32, 0, 0, 0, 0, c["name"])
        n_meta += 1
    champ_data = (bytes([0]) + struct.pack("<I", len(roster)) + groups
                  + bytes([0]) + pack_compact(n_meta) + meta)
    shown = [(e, name) for e, name in ENCOUNTERS if e not in set(hidden)]
    n = len(shown)
    encounters = (b"\x00"
                  + struct.pack("<I", n) + b"".join(struct.pack("<I", e) for e, _ in shown)
                  + struct.pack("<I", n) + b"".join(
                      struct.pack("<I", 0 if "Tutorial" in name else (1 << 21) | (1 << 17))
                      for _, name in shown)
                  + struct.pack("<I", n) + b"\x00" * n
                  + struct.pack("<I", n) + b"\x00\x00\x00\x00" * n
                  + struct.pack("<I", 0)
                  + struct.pack("<I", 0) + b"\x00" + pack_compact(0) + pack_compact(0)
                  + struct.pack("<Q", 0))
    settings = [_setting("FeaturedMap_PVP", "0x40000399"), _setting("FeaturedMap_BOTS", "0x40000B6A")]
    game_settings = b"\x00" + pack_compact(len(settings)) + b"".join(settings)
    svc = SVC_PLAYER_SYSTEM
    return [
        ("set local player (0xeb)", build_message(svc, EVT_SET_LOCAL_PLAYER, set_player)),
        ("item statuses (0x20b8)", build_message(svc, 0x20B8, item_statuses)),
        ("champion data (0x20ed)", build_message(svc, EVT_CHAMPION_DATA, champ_data)),
        ("character list (0x209d)", build_message(svc, EVT_MASTER_CHARACTER_LIST, char_list)),
        ("encounter info (0x2024)", build_message(svc, EVT_DELIVER_ENCOUNTER_INFO, encounters)),
        ("server options (0x216a)", build_message(svc, 0x216A, EMPTY_TABLE_EVENT)),
        ("achievements (0x2120)", build_message(svc, 0x2120, EMPTY_TABLE_EVENT + struct.pack("<I", 0))),
        ("account tables (0x218b)", build_message(svc, 0x218B, EMPTY_TABLE_EVENT + game_settings)),
        ("account flags (0x215d)", build_message(svc, 0x215D, b"\x00" + struct.pack("<I", 1) + b"\x00")),
        ("account character set (0xce)", build_message(svc, EVT_ACCOUNT_CHARACTER_SET,
                                                       character_set(player_name))),
        ("account level (0x2080)", build_message(
            svc, 0x2080, b"\x00" + struct.pack("<6I2f", account_level, account_level, 0, 100, 0, 0, 0.0, 0.0))),
    ]


# ---- queue / lobby / match entry -----------------------------------------------------

def joined_queue(did, qflags):
    return build_message(SVC_PLAYER_SYSTEM, 0x20C0, b"\x00" + struct.pack("<IIffI", did, qflags, 0.0, 0.0, 0))


def match_found(max_players=1, timeout=30):
    return build_message(SVC_PLAYER_SYSTEM, 0x20FA, b"\x00" + struct.pack("<II", max_players, timeout))


def players_accepted(n=1):
    return build_message(SVC_PLAYER_SYSTEM, 0x20AD, b"\x00" + struct.pack("<I", n))


def lobby_room_created(did, qflags):
    return build_message(SVC_PLAYER_SYSTEM, 0x2028, b"\x00" + struct.pack("<IIII", did, qflags, 0, 0))


def lobby_player(champion, name, team, room_id, player_id=LOCAL_PLAYER_ID, locked=False):
    """0x2029 one lobby slot (serializer rva 0x4479b0). 2026-10-18: u32 team (+0x68) | u32 index (+0x6c) |
    u64 player (+0x70) | StringInfo name (+0x78) | u8 is bot (+0x9c) | u32 character (+0xa0) | u32 (+0xa4) |
    u8 locked (+0xa8, probable: Flash UpdateLobbyState has abLockedStatus after the character) | ..."""
    s = b"\x00"
    tail = (struct.pack("<IQI", 0, 0, 0) + string_info("") + pack_compact(0)
            + struct.pack("<I", 0) + pack_compact(1) + struct.pack("<I", champion))
    body = (b"\x00" + s
            + struct.pack("<IIQ", team, 0, player_id) + string_info(name)
            + b"\x00" + struct.pack("<II", champion, 0) + (b"\x01" if locked else b"\x00")
            + struct.pack("<II", room_id, 1) + struct.pack("<7I", *([0] * 7))
            + tail)
    return build_message(SVC_PLAYER_SYSTEM, 0x2029, body)


def lobby_state(did, qflags, champion, room_id, teams=0, per_team=0, my_team=0, available=None):
    """0x204C lobby state (serializer rva 0x445810; apply 0x8b8970 -> CLobbyManager 0xabde80).
    2026-10-18 (static analysis): u8 0 | u32 number of teams (lobby+0xac) | u32 players per team (+0xb0) |
    u32 encounter | u32 qflags | u64 | u32 my team (+0xbc) | u32 room | lists. The lobby UI (Flash PvPLobby,
    the champion select) only gets the encounter details when the number of teams is not 0."""
    owned = struct.pack("<IIIBI", champion, 2, 1, 1, 1)
    body = (b"\x00" + struct.pack("<II", teams, per_team) + struct.pack("<II", did, qflags)
            + struct.pack("<QII", 0, my_team, room_id)
            + struct.pack("<I", 1) + owned
            + struct.pack("<I", len(available or [champion]))
            + b"".join(struct.pack("<I", c) for c in (available or [champion]))
            + b"\x00\x00")
    return build_message(SVC_PLAYER_SYSTEM, 0x204C, body)


def end_room_check(room_id):
    return build_message(SVC_PLAYER_SYSTEM, 0x2016, b"\x00" + struct.pack("<I", room_id))


def all_loaded(room_id):
    return build_message(SVC_PLAYER_SYSTEM, 0x206D, b"\x00" + struct.pack("<I", room_id))


def match_start():
    return build_message(SVC_PLAYER_SYSTEM, 0x2053, b"\x00" + struct.pack("<III", 0, 0, 0))


def loading_percent(team, percent, room_id):
    body = (b"\x00" + struct.pack("<II", 1, team) + struct.pack("<II", 1, 0)
            + struct.pack("<II", 1, percent) + struct.pack("<I", room_id))
    return build_message(SVC_PLAYER_SYSTEM, 0x2031, body)


def enter_match(encounter_did, champion, packs, extra_champions=()):
    """0x20AF (handler 0x699f00): u8 base | u32 | u32 n + champion DIDs |
    u32 n + pack ids | u32 encounter DID. The champion list is every champion
    whose data the match needs (extra ones: cinematic actors such as Catwoman)."""
    champs = [champion] + [c for c in extra_champions if c != champion]
    body = (b"\x00" + struct.pack("<I", 0)
            + struct.pack("<I", len(champs)) + b"".join(struct.pack("<I", c) for c in champs)
            + struct.pack("<I", len(packs)) + b"".join(struct.pack("<I", p) for p in packs)
            + struct.pack("<I", encounter_did))
    return build_message(SVC_PLAYER_SYSTEM, 0x20AF, body)


# ---- world objects ----------------------------------------------------------------

def create_object(object_id, class_id, now, sequence=1, position=None, heading=0.0, speed=0.0,
                  tele_seq=1, second_seq=0, module=(1, 1), iid_properties=None, properties=None,
                  unknown64=0, facing_offset=0.0):
    """Object bundle = batch 0x4 to the object's id with 0xF2 descriptor,
    0xB0 position/motion and 0xBC properties (see the old server for every
    field). second_seq must be 0 until the client reports load complete
    (1 afterwards): the smooth movement branch crashes during loading."""
    descriptor = struct.pack("<IQI", class_id, unknown64, sequence)
    if position:
        region, lb_x, lb_y, cell, x, y, z = position
        if module:
            module_seq, module_type = module
            head = bytes([0x62, module_seq, module_type, 0x0F])
        else:
            # No movement module (flag 0x20 left out): for static props. The
            # module (type 1 = rigid-body CHARACTER replay) is what places a
            # character; props have no character physics and stayed invisible.
            head = bytes([0x42, 0x0F])
        pos = (head
               + struct.pack("<d", now)
               + build_position(region, lb_x, lb_y, cell, x, y, z) + struct.pack("<H", 0)
               + bytes([0x80 | 0x2C, 0x18]) + struct.pack("<ff", heading, speed)
               + struct.pack("<h", int(round(facing_yaw(heading + facing_offset) * 10000.0)))
               + bytes([tele_seq, second_seq]))
    else:
        pos = bytes([0]) + struct.pack("<H", 0)
    entries = [(pid, KIND_IID, iid) for pid, iid in (iid_properties or {}).items()] + list(properties or [])
    body = build_batch([(0xF2, descriptor), (0xB0, pos), (0xBC, property_table(entries))])
    return build_message(object_id, 0x4, body)


def scenery_module(cfg):
    """[combat] scenery_module -> None (no movement module) or (sequence, type)."""
    v = cfg["combat"].get("scenery_module", "none")
    if not v or v == "none":
        return None
    return int(v[0]), int(v[1])


def remove_object(object_id):
    """Event 0x3 to the object: hidden at once, freed 30 s later."""
    return build_message(object_id, 0x3, bytes(1))


def champion_properties(name, team, icon, level=1, xp=0, skill_points=1, move_speed=None):
    """move_speed: property 0x100005E4 (movement speed; drones carry 3.0 in their
    world state, items +0.05..0.2). The client copies it into the motion
    component's walk-animation cap (+0x2d0); without it Batman's cap is 0 and he
    slides (diag.log 2026-10-13: drones 3.0, Batman 0.0). None = not sent."""
    extra = [] if move_speed is None else [(0x100005E4, KIND_F32, float(move_speed))]
    return extra + [
        (0x10000064, KIND_IID, LOCAL_PLAYER_ID),   # Character_ControllableAgentToPlayer_InstanceID
        (0x00000956, KIND_ENUM, 0x10000016),       # lighting environment
        (0x1000009C, KIND_INT, team),              # PVP_Team
        (0x100000FA, KIND_ENUM, 4),                # LifeState = Alive (else nameplate hidden / "dead")
        (0x10000167, KIND_INT, level),             # Level
        (0x10000142, KIND_INT, xp),                # XP
        (0x100001AF, KIND_INT, skill_points),      # SkillPoints
        (0x1000035E, KIND_F32, 0.0),               # Upgrade_Currency
        (0x000003CE, KIND_STRING, name),           # Name
        (0x10000433, KIND_STRING, name),           # Character_Name
        (0x10000384, KIND_DID, icon),              # Character_SmallIcon
        (0x10000338, KIND_DID, icon),              # portrait (guess)
        (0x10000337, KIND_DID, icon),              # large icon (guess)
    ]


LIFE_ALIVE, LIFE_DEAD = 4, 2


def creature_properties(team, alive=True):
    """Drones / creatures: team (enemy = 2) and LifeState (nameplate needs Alive)."""
    return [(0x1000009C, KIND_INT, team),
            (0x100000FA, KIND_ENUM, LIFE_ALIVE if alive else LIFE_DEAD)]


PLAYER_PROPERTIES = [(0x00000956, KIND_ENUM, 0x10000016)]   # lighting environment


def player_late_properties(encounter_did):
    """Only on re-sends: the map manager listens for a CHANGE of 0x100001d3."""
    return [(0x100001D3, KIND_DID, encounter_did)]


EVT_START_SCRIPTLETS = 0x8D
PROP_SCRIPT_TARGET = 0x108      # script variable: target instance id (u64)


def scriptlet_entry(did, instance, originator=0, packed=False, variables=None, second=0):
    """One "run this scriptlet" order (list reader rva 0x12d4a0, entry stride 0x60).

      DID         u8 high byte | compact low 24 bits (rva 0xfeb20)
      instance    compact (rva 0x43f40). A new number starts a new run; a number
                  that is still running only gets signalled (rva 0x57b510).
      parameters  rva 0x2837e0:
                    run flags   u32 (u8 when the stream is packed, flag 0x800)
                    field mask  u8: 0x01 originator u64, 0x20 2nd iid u64,
                                0x02 variable table, 0x04 f32, 0x10 f32,
                                0x08 u32, 0x40 u32 (all left out here)
                    [0x01] originator u64: the client skips the order when it
                                equals its own local id (rva 0x2279d0)
                    start time  f64 (the client zeroes it, rva 0x227e7b)
      signals     bit set (rva 0x100750): compact bit count, then the bytes
    Packed = inside an object bundle (batch sub-events have no base byte and
    use the packed widths, see rva 0x70d380)."""
    out = bytes([did >> 24]) + pack_compact(did & 0xFFFFFF) + pack_compact(instance)
    out += bytes([0]) if packed else struct.pack("<I", 0)
    mask = (0x01 if originator else 0) | (0x02 if variables else 0) | (0x20 if second else 0)
    out += bytes([mask])
    if originator:
        out += struct.pack("<Q", originator)
    if second:
        out += struct.pack("<Q", second)      # [0x20] second instance id (the target object)
    if variables:
        # script variables = a property table (rva 0x109950 -> 0x103330); the
        # client's own skills put the target there as property 0x108 (rva 0x281269)
        out += property_table(variables)
    out += struct.pack("<d", 0.0)
    return out + pack_compact(0)


def start_scriptlets(entity_id, entries, originator=0, variables=None, second=0):
    """Event 0x8D to an entity (serializer rva 0x43c030, handler rva 0x234f20 ->
    the entity's script component +0x10): u8 base | compact count | entries.
    entries = [(scriptlet DID, instance number), ...]."""
    body = b"\x00" + pack_compact(len(entries)) + b"".join(
        scriptlet_entry(did, inst, originator, variables=variables, second=second) for did, inst in entries)
    return build_message(entity_id, EVT_START_SCRIPTLETS, body)


VITALS_FIRST_LIST = False   # set from [match] vitals_first_list at server start


def vitals(object_id, pairs, first=None):
    """0x42 (only to objects WITH a vitals component, else the client crashes).
    u8 0 | u8 n | n x (u16, u16) | u8 n | n x (u16 cur, u16 max) | u16 0. The HUD
    shows the sum of both lists. The values used to go in the second list only;
    with first=True they go in the first (2026-10-14: the client said "not
    enough Will" for Q with 100/100 shown, as if it read the first list)."""
    first = VITALS_FIRST_LIST if first is None else first
    data = b"".join(struct.pack("<HH", int(cur) & 0x7FFF, int(mx) & 0x7FFF) for cur, mx in pairs)
    zeros = bytes(len(data))
    a, b = (data, zeros) if first else (zeros, data)
    body = bytes([0, len(pairs)]) + a + bytes([len(pairs)]) + b + bytes([0, 0])
    return build_message(object_id, 0x42, body)


def cinematic(did):
    return build_message(LOCAL_PLAYER_ID, 0x20F5, bytes(1) + struct.pack("<II", 0x1, did))


# ---- HUD / objectives / dialogue ---------------------------------------------------

def hud_element(element, event, highlight=0, highlight_did=0):
    return build_message(LOCAL_PLAYER_ID, 0x213D,
                         b"\x00" + struct.pack("<IIII", element, event, highlight, highlight_did))


def objective(objective_id, text=None, active=None, state=None, count=None, count_max=None,
              category=None, sort_order=None, optional=None, banner=None):
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
        flags |= 0x1000000; out += string_info(banner)
    return struct.pack("<I", flags) + out


def objective_category(category_id, title, description="", sort_order=0, state=None, visible=True):
    flags, out = 0x01, struct.pack("<I", category_id)
    if state is not None:
        flags |= 0x08; out += struct.pack("<I", state)
    flags |= 0x10; out += string_info(title)
    flags |= 0x02; out += string_info(description or title)
    flags |= 0x04; out += struct.pack("<I", sort_order)
    flags |= 0x20; out += bytes([1 if visible else 0])
    return struct.pack("<I", flags) + out


def objective_list(objectives, categories=()):
    body = (b"\x00" + struct.pack("<I", len(objectives)) + b"".join(objectives)
            + struct.pack("<I", len(categories)) + b"".join(categories))
    return build_message(LOCAL_PLAYER_ID, 0x2034, body)


def objective_update(obj):
    objective_id = struct.unpack_from("<I", obj, 4)[0]
    return build_message(LOCAL_PLAYER_ID, 0x2009, b"\x00" + struct.pack("<I", objective_id) + obj)


def start_conversation(key, speaker=CHAMPION_AGENT_ID, instance_id=0xFFFFFFFF):
    body = (bytes(1) + struct.pack("<QIII", 0, 1, key, 1) + struct.pack("<Q", speaker)
            + bytes([1]) + struct.pack("<I", instance_id))
    return build_message(LOCAL_PLAYER_ID, 0x2001, body)


def tutorial_hint(hint_id, force_open=True):
    blob = struct.pack("<I", hint_id) + bytes([1 if force_open else 0])
    return build_message(LOCAL_PLAYER_ID, 0x2, bytes(1) + struct.pack("<II", 0x1000027F, len(blob)) + blob)


NOTICE_SHOW_ANNOUNCEMENT = 0x100002EB  # GM_Character.RecvNotice_ShowAnnouncement (reader 0x8c2fa0)
NOTICE_CLEAR_ANNOUNCEMENT = 0x100002EC


def _notice(notice_id, blob):
    return build_message(LOCAL_PLAYER_ID, 0x2, bytes(1) + struct.pack("<II", notice_id, len(blob)) + blob)


def show_announcement(text, a=1, b=0, c=0, d=-1, e=-1, flag=0):
    """The big centre-screen announcement: StringInfo text | u32 a | u32 b |
    u32 c | i32 d | i32 e | u8 flag (the client's own kill announcements fill
    the same fields; a must not be 0)."""
    return _notice(NOTICE_SHOW_ANNOUNCEMENT, string_info(text) + struct.pack("<IIIiiB", a, b, c, d, e, 1 if flag else 0))


def clear_announcement():
    return _notice(NOTICE_CLEAR_ANNOUNCEMENT, b"")


def timeline_banner(title, subtitle="", event_id=1, iid=LOCAL_PLAYER_ID, now=0.0, audience=7):
    """The mission timeline banner: notices 0x100002AF and 0x100002B1 (both
    needed before any banner shows), then 0x10000424 AddTimelineBanner:
    u32 event | u64 iid | u32 | u32 | u32 | u8 | u32 | f64 time | u8 |
    u32 n | n x (StringInfo title | StringInfo subtitle | u32 audience) | f64."""
    enable = struct.pack("<Q", iid)
    desc = (struct.pack("<IQ", event_id, iid) + struct.pack("<IIIBI", 0, 0, 0, 0, 0) + struct.pack("<d", now)
            + b"\x00" + struct.pack("<I", 1) + string_info(title) + string_info(subtitle)
            + struct.pack("<I", audience))
    return [("timeline banners on (0x100002af)", _notice(0x100002AF, enable)),
            ("timeline banners on (0x100002b1)", _notice(0x100002B1, enable)),
            (f"timeline banner '{title}' (0x10000424)", _notice(0x10000424, desc + struct.pack("<d", now)))]


def objective_tracker_enabled(enabled=True):
    return build_message(LOCAL_PLAYER_ID, 0x2075, bytes([0, 1 if enabled else 0]))


# ---- the end of a match ----------------------------------------------------------------
# (2026-10-15, static analysis of the client; see docs/reverse-engineering.md "Ending a match")
NOTICE_MATCH_ENDED = 0x1000000E      # GM_Encounter.RecvNotice_NotifyMatchEnded (reader rva 0x941750)
EVT_END_OF_MATCH_STATS = 0x2045      # end-of-match page (exec 0x8b2bd0 -> 0xa91bf0)
EVT_COMPLETED_ENCOUNTERS = 0x214B    # GM_Encounter.RecvNotice_UI_CompletedEncounters (0xa30cd0)


def match_ended(winning_team, seconds, b=0, d=0, e=0.0):
    """Notice 0x1000000E to the local player: u32 winning team | u32 | f32 match
    seconds | u32 | f32. The end page compares the winning team with the
    player's PVP_Team (0x1000009C): equal = VICTORY."""
    blob = struct.pack("<IIfIf", winning_team, b, float(seconds), d, float(e))
    return build_message(LOCAL_PLAYER_ID, 0x2, bytes(1) + struct.pack("<II", NOTICE_MATCH_ENDED, len(blob)) + blob)


def _end_stats_entry(player_iid, champion_iid):
    """One player's end-of-match entry (reader 0x8776a0), all zero / empty."""
    empty = string_info("")
    q = lambda n: struct.pack("<%dQ" % n, *([0] * n))
    i = lambda n: struct.pack("<%dI" % n, *([0] * n))
    head = struct.pack("<QQQII", player_iid, champion_iid, player_iid, 0, 0)
    sub = struct.pack("<IQI", 0, 0, 0) + empty + wstring("") + i(1) + pack_compact(0)     # 0x86fb20
    mid = i(1) + b"\x00\x00" + b"\x00\x00" + empty + i(1) + i(3)
    stats = (struct.pack("<QBI", 0, 0, 0) + q(14) + i(2) + q(6) + i(1) + q(8) + i(1) + q(6) + i(1)
             + empty + empty + q(21) + i(2))                                               # 0x866650 (ends f32, f32)
    tail = i(1) + b"\x00" + b"\x00"
    return head + sub + mid + stats + tail


def end_of_match_stats(seconds, player_iid=LOCAL_PLAYER_ID, champion_iid=CHAMPION_AGENT_ID):
    """0x2045 to the player system: u8 0 | u32 n | n entries | f32. The end
    page fills in only once it has these AND the match-ended notice."""
    body = bytes(1) + struct.pack("<I", 1) + _end_stats_entry(player_iid, champion_iid) + struct.pack("<f", float(seconds))
    return build_message(SVC_PLAYER_SYSTEM, EVT_END_OF_MATCH_STATS, body)


def completed_encounters(dids, last_played=0, flags=0):
    """0x214B: u8 0 | u32 n | n x u32 encounter | u32 last played | u32 flags.
    Tutorial 2 (0x40000A81) needs Tutorial 1 (0x40000991) in this list."""
    dids = list(dids)
    body = (bytes(1) + struct.pack("<I", len(dids)) + b"".join(struct.pack("<I", d) for d in dids)
            + struct.pack("<II", last_played, flags))
    return build_message(SVC_PLAYER_SYSTEM, EVT_COMPLETED_ENCOUNTERS, body)


EVT_EXIT_LOBBY = 0x2021              # RecvEvt_DeliverNotifyPlayerToExitLobby (handler 0xabc480)


def exit_lobby(room_id):
    """0x2021 to the player system: u8 0 | u32 room id (as in 0x2028 / 0x2029).
    The client leaves the match world (it answers with 0x12D) and goes home."""
    return build_message(SVC_PLAYER_SYSTEM, EVT_EXIT_LOBBY, b"\x00" + struct.pack("<I", room_id))


def server_preferences(prefs):
    """0x216A "server options" to the player system: the client stores each
    entry in its UserPreferences.ini (handler 0xa742d0). prefs = [(name, bool)]:
    u8 0 | u8 size class 0 | compact n | n x (compact len + ASCII name | u16 BE
    type 0x16 | u8 value)."""
    body = b"\x00\x00" + pack_compact(len(prefs))
    for name, value in prefs:
        body += pack_compact(len(name)) + name.encode("ascii") + struct.pack(">H", 0x16) + bytes([1 if value else 0])
    return build_message(SVC_PLAYER_SYSTEM, 0x216A, body)
