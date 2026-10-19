"""Builds InfiniteCrisis_patched.exe from the untouched client (same four
patches as the original project's tools/patch_client.py) and checks that an
existing patched exe matches the server key."""
import hashlib
import os

from .crypto import generate_key_pem, load_key

KNOWN_SIZE = 26500568
KNOWN_SHA256 = "463adffff7dfc8e6c184eff0598b064ccee75e2155ff0f4a3c3b5fd337a33e31"

# (file offset, original bytes, patched bytes, description)
PATCHES = [
    (0xBE3862, bytes.fromhex("568bcbe86625b2ff"), bytes.fromhex("33c0909090909090"),
     "Oodle: outgoing game packets uncompressed (rva 0xbe4462)"),
    (0x67EF34, bytes.fromhex("83e20c80fa0c"), bytes.fromhex("83e20880fa08"),
     "dialog gate: conversations without 'match started' (rva 0x67fb34)"),
    (0x11DB16C, bytes.fromhex("00002040"), bytes.fromhex("cdcc4c3e"),
     "lighting re-evaluation 2.5 s -> 0.2 s (rva 0x11dcd6c)"),
    # ---- skills (2026-10-14) ------------------------------------------------------
    # GM_Advancement has no handlers in this client (its scripts never register
    # any), so every query answers with its default and every notice dies. What
    # each dispatcher is, from how the client uses it (the id table at
    # 0x1467100 lists the ids, not their order of names):
    #   0x50e580 (id 0x1000006A): InqCanRankSkill(agent, slot, &eError) (2026-10-16:
    #     these two were swapped in the first notes). Natives: UI
    #     rank query rva 0x524500 (bursts for slots 0-5 on every HUD refresh,
    #     and slot 1 on Ctrl+Q); HUD C++ skill loop rva 0x67c8b1.
    #   0x50e840 (id 0x10000063): InqSkillRank(agent, slot, &rank) (Flash rank query) from the
    #     "+" (native rva 0x524b00); no handler = error 0xe7f, so the click stops.
    #   0x50e6d0 (id 0x1000023C): next recommended skill (agent, &slot): HUD loop
    #     rva 0x67c8c8 and the "rank recommended" key rva 0x60b6b9.
    #   0x50e9a0 (id 0x1000009B): RankSkill(agent, slot): native rva 0x524e80
    #     (after InqCanRankSkill succeeds) and rva 0x60b6dc.
    # The server keeps the ranks in the champion's int property 0x100006C1
    # (getter rva 0x21c990): 4 bits per slot 0-6, top 4 bits = recommended slot + 1.
    #
    # Ping cave (rva 0x48bc9c): sends a player ping (event 0x2136, sender rva
    # 0x487e60) with type 0x52414E4B ("KNAR") and target = the slot, then calls
    # the RankSkill dispatcher. Used by both RankSkill call sites.
    (0x48B09C, bytes([0xCC]) * 64, bytes.fromhex(
        "558bec83ec046a00684b4e41526a00ff7510684b4e4152684b4e41528d45fc50e89fc1ffff83c41cff7514ff7510ff750cff7508"
        "e8cb2c080083c4108be55dc3"),
     "skills: ping cave, RankSkill goes to the server (rva 0x48bc9c)"),
    (0x52431A, bytes.fromhex("e8819afeff"), bytes.fromhex("e87d6df6ff"),
     "skills: the '+' RankSkill native calls the ping cave (rva 0x524f1a)"),
    (0x60AADC, bytes.fromhex("e8bf32f0ff"), bytes.fromhex("e8bb05e8ff"),
     "skills: 'rank recommended skill' calls the ping cave (rva 0x60b6dc)"),
    # Cave A (rva 0x5e7924) + B (rva 0x7369d4): InqSkillRank, then for the local
    # champion (rva 0x45d670) and slots 0-6 the slot's nibble of the property is
    # the rank (0 when the property is missing). Without it the UI got the
    # dispatcher's garbage (3711 = 0xe7f) as the rank, and a "+" click, which
    # first asks the rank, stopped there (diag 2026-10-14).
    (0x5239BF, bytes.fromhex("e8bc9ffeff"), bytes.fromhex("e860330c00"),
     "skills: UI rank query asks cave A (rva 0x5245bf)"),
    (0x5E6D24, bytes([0xCC]) * 73, bytes.fromhex(
        "5589e556ff7514ff7510ff750cff7508e8476cf2ff83c41089c6e82d5de7ff85c074218b88000100003b4d0875168b8804"
        "0100003b4d0c750b837d10069090e999f0140089f05e5dc3"),
     "skills: cave A, rank query + local champion check (rva 0x5e7924)"),
    # 2026-10-16: for slots > 6 (D = 7, F = 8, ...) the HUD loop's "can rank"
    # value stayed 0 (= the "+" shows): those now get 0x10000022
    # (SkillRank_NotHighEnoughLevel) at the end of cave B (cave A jumps there for every slot).
    (0x735DD4, bytes([0xCC]) * 69, bytes.fromhex(
        "6a005468c106001050e8ae5faeff83c40c5a84c0750231d28b4d10c1e102d3ea83e20f8b4d14891189f05e5dc3"
        "837d10060f86c9ffffff8b4d14c7012200001089f05e5dc3"),
     "skills: cave B, rank from champion property 0x100006C1 (rva 0x7369d4)"),
    (0x67BCB1, bytes.fromhex("e8ca1ce9ff"), bytes.fromhex("e86eb0f6ff"),
     "skills: HUD skill loop asks cave A for the rank (rva 0x67c8b1)"),
    # Cave C (rva 0x725a64): recommended skill for the HUD loop (esi = its agent).
    (0x724E64, bytes([0xCC]) * 57, bytes.fromhex(
        "5589e5ff7510ff750cff7508e85b8cdeff83c40c506a005468c106001056e8096fafff83c40c5a84c0740bc1ea1c74064a8b4d108911585dc3"),
     "skills: cave C, recommended skill from property 0x100006C1 (rva 0x725a64)"),
    (0x67BCC8, bytes.fromhex("e8031ee9ff"), bytes.fromhex("e897910a00"),
     "skills: HUD skill loop asks cave C for the recommended skill (rva 0x67c8c8)"),
    # Cave E (rva 0x72f7e4 -> 0x71f968): InqCanRankSkill answers "no error" for
    # the recommended slot, so the "+" click goes on to RankSkill.
    (0x523FCA, bytes.fromhex("e8719cfeff"), bytes.fromhex("e815ac2000"),
     "skills: InqCanRankSkill asks cave E (rva 0x524bca)"),
    (0x72EBE4, bytes([0xCC]) * 45, bytes.fromhex(
        "5589e556ff7514ff7510ff750cff7508e847f0ddff83c41089c6e86dded2ff85c07405e95c01ffff89f05e5dc3"),
     "skills: cave E1, InqCanRankSkill (rva 0x72f7e4)"),
    # 2026-10-15: E2 answers "no error" for every slot whose nibble of 0x100006C1
    # is 0 (the server's "may be ranked now" flag), not only the recommended one,
    # so the tutorial can offer Q or W for one skill point.
    # 2026-10-16 (static analysis): the IDs were swapped -- cave E answers the
    # RANK query Flash uses (SkillsPanel.QuerySkillRanks), so it gave rank 0 to
    # every slot flagged "may rank now" and 3711 to the others: learned skills
    # and the basic attack looked locked (grey). E2 now returns the real rank
    # (GetSkillRank VA 0x863ce0) for the local champion.
    (0x71ED68, bytes([0xCC]) * 51, bytes.fromhex(
        "8b88000100003b4d08751d8b88040100003b4d0c7512ff751050e85943d4ff83c4088b4d1489019089f05e5dc3"
        "cccccccccccc"),
     "skills: cave E2, the real skill rank for the UI (rva 0x71f968)"),
    # Cave D (rva 0xfb4fb8 -> 0xfaafb8): the HUD skill loop (rva 0x67c640) only
    # runs for slots marked dirty, and nothing marks them in this client. Before
    # each call (rva 0x67d202, every frame) the cave reads the property; when it
    # changed (missing = 0; last value kept at rva 0x190ef00, unused end of .data) it marks
    # slots 0-7 dirty, so the HUD gets RecvNotice_UI_SkillUpdate with the ranks.
    # 2026-10-15: slots 6-7 too (was 0-5): slot 7 = Secondary1 = the Stolen
    # Power on D, whose skill the server gives as champion property 0x100008F0.
    (0x67C602, bytes.fromhex("e839f4ffff"), bytes.fromhex("e8b17d9300"),
     "skills: HUD update calls cave D first (rva 0x67d202)"),
    (0xFB43B8, bytes([0xCC]) * 43, bytes.fromhex(
        "e8b3864aff85c0741d6a005468c106001050e8c17926ff83c40c5a84c0750231d2e9da5fffffe95d766cff"),
     "skills: cave D1, read the property every frame (rva 0xfb4fb8)"),
    (0xFAA3B8, bytes([0xCC]) * 52, bytes.fromhex(
        "e800000000593b91433f960074218991433f9600c781eba97c0001010101c781efa97c0001010101c681f3a97c0001"
        "e954166dff"),
     "skills: cave D2, mark skill slots 0-8 dirty when it changed (rva 0xfaafb8)"),
]
# ---- props (2026-10-14) -----------------------------------------------------------
# WorldEntityFactory (rva 0x14f1f0) builds an object from an ENTITY class
# (0x40...) and looks up that entity's world state (rva 0x14be10: edi = entity,
# eax = world state; diag 2026-10-14 11:17: Door 0x40000B0F -> 0x2E0010F3). A
# bare world state (0x2E...) sent as the class builds nothing, silently: the
# street vehicle (0x2E000AAB) and the meteors (rock 0x2E000BB3, dust 0x2E0007D4) have no entity.
# Patch: class 0x4A-0x4F + the world state's low 24 bits means "build carrier
# entity N (N = prefix - 0x4A, from a 6-entry table) with world state 0x2Exxxxxx".
#   cave X (rva 0x997f5a), at the class read (rva 0x14f20e): remembers the world
#     state in the unused .data tail (rva 0x190ef40) and swaps the class for the
#     carrier from the table (rva 0xc18f40);
#   cave Y (rva 0xfbefbc), after the world-state lookup (rva 0x14f3b4): uses the
#     remembered one (and clears it).
# 2026-10-14 11:36: with the Door as carrier the vehicle is built but fails at
# component creation (step 3); the table lets one run try 6 carriers.
# 2026-10-14 12:05: all failed in the same component (creator rva 0x204760,
# init rva 0x1693a0), which reads the class from the creation info (+0x30):
# it still held 0x4Axxxxxx. Writing the carrier there did not help (12:15):
# that component resolves the .entity (0x2D...) from it, and got the Door's
# while the world state was the vehicle's. The map's own props (diag 12:25)
# are built with the bare world state there, so cave X now writes the world
# state (0x2E...) into the creation info and keeps the carrier only for the
# factory's entity record.
PROP_CAVE_X = 0x99735A
PROP_TABLE = 0xC18340
PROP_CARRIERS_DEFAULT = (0x40000B0F, 0x40000289, 0x400001BD, 0x4000081B, 0x40000B0A, 0x40000092)
PATCHES += [
    (0x14E60E, bytes.fromhex("8b7f3057897d0c"), bytes.fromhex("e8478d84005790"),
     "props: class read -> cave X (rva 0x14f20e)"),
    (PROP_CAVE_X, bytes([0xCC]) * 54, bytes.fromhex("8b473089c1c1e91883e94a83f9057720e8000000005a25ffffff000d0000002e8982d16ff7008947308b848ad10f280089c7897d0cc3"),
     "props: cave X, class 0x4A-0x4F -> carrier + remembered world state (rva 0x997f5a)"),
    (PROP_TABLE, bytes([0xCC]) * 24, b"".join(c.to_bytes(4, "little") for c in PROP_CARRIERS_DEFAULT),
     "props: carrier table (rva 0xc18f40)"),
    (0x14E7B4, bytes.fromhex("8b45fc83c408"), bytes.fromhex("e803fce60090"),
     "props: world-state lookup -> cave Y (rva 0x14f3b4)"),
    (0xFBE3BC, bytes([0xCC]) * 40, bytes.fromhex(
        "5983c408518b45fce800000000598b9177ff940085d2740f89d08945fcc78177ff940000000000c3"),
     "props: cave Y, use the remembered world state (rva 0xfbefbc)"),
    # 2026-10-14 15:35 (diag --create): the vehicle sent as its bare world state
    # builds its model but is never placed; the Door carrier is placed but the
    # model component (init rva 0x1693a0) looked up the .entity of the class
    # 0x4Axxxxxx and found none. Cave Z: that lookup uses 0x2E + the low 24
    # bits for classes 0x4A-0x4F, i.e. the vehicle's own model on the Door.
    (0x1687AA, bytes.fromhex("8b46305750"), bytes.fromhex("e88d631600"),
     "props: model lookup -> cave Z (rva 0x1693aa)"),
    (0x2CEB3C, bytes([0xCC]) * 31, bytes.fromhex("8b463089c2c1ea1883ea4a83fa05770a25ffffff000d0000002e5a5750ffe2"),
     "props: cave Z, class 0x4A-0x4F -> world state 0x2E for the model (rva 0x2cf73c)"),
]

# ---- minimap image (2026-10-14 17:25, diag --minimap) -------------------------
# The map manager M = [[0x17758d4]+0x50] turns the encounter DID into the map
# image (rva 0x64c2c0, thiscall, 1 arg) and hands it to the HUD; normally a
# change of the local player's property 0x100001D3 calls it, which never comes,
# so the minimap stayed the green placeholder (and the fog-of-war blocker map,
# which reads M's map data, was never drawn). Calling it from the diag made
# the real map show. The HUD's "re-deliver the map" (rva 0x60d810, this =
# M+0x18, called once when the HUD loads) now asks for it when none is loaded.
# 2026-10-14 18:34 (diag --notes): the note manager's tick (rva 0x66a7c0) also
# needs [M+0xc8] = "map delivered to the HUD", which only the re-deliver sets
# ([esi+0xb0]); without it no note ever got a position. The cave sets it too.
MINIMAP_ENCOUNTER = 0x40000991          # Tutorial 1
# 2026-10-18 01:10 (tester: `ic.py patch` refused, "unexpected bytes at 0x99735c"): fase3-jb put cave N at
# file 0x99735C, two bytes into cave X (props, 0x99735A-0x997390). It now uses the free 0xCC padding at file
# 0x4C4380 (rva 0x4c4f80, 48 bytes); tests/test_patcher_layout.py checks that no two patches overlap.
MINIMAP_CAVE_N = 0x4C4380
PATCHES += [
    (0x60CC13, bytes.fromhex("807e54007413"), bytes.fromhex("e9a447000090"),
     "minimap: HUD re-deliver -> cave M (rva 0x60d813)"),
    (0x6113BC, bytes([0xCC]) * 35, bytes.fromhex(
        "807e54000f8553b8ffff8d4ee8" "e8b22febff"
        + "e8eda20300c686b000000001e94db8ffff"),
     "minimap: cave M, no map loaded -> load the encounter's map image, mark it delivered (rva 0x611fbc)"),
    # 2026-10-18 00:44 (tester: Coast City v AI loads very dark): cave M pushed Tutorial 1 (MINIMAP_ENCOUNTER)
    # for every map, so the fog-of-war blocker map of another map was Tutorial 1's. Cave N (rva 0x4c4f80,
    # called where cave M pushed the constant) pushes the encounter of the lobby manager instead
    # ([[VA 0x1b77068]+0xb4], set by 0x204C; found position-independently: the client runs with ASLR),
    # Tutorial 1 when there is none. It keeps ecx (the map manager) for the thiscall that follows.
    (MINIMAP_CAVE_N, bytes([0xCC]) * 36, bytes.fromhex(
        "5ae8000000005805e2202b018b0085c0740a8b80b400000085c07505b8" + MINIMAP_ENCOUNTER.to_bytes(4, "little").hex()
        + "50ffe2"),
     "minimap: cave N, the lobby's encounter for the map image (rva 0x4c4f80)"),
]

# ---- minimap notes: the object's team (2026-10-14 17:57, diag --notes) --------
# The note reader (rva 0x64b150) reads the object's PVP_Team with rva 0x188820
# (store [entity+0x38], vtable +0x58), which finds nothing for the server's
# properties (al = 0 for every object, Batman too), so the team was -1 and
# every object an "enemy" that the minimap never draws. The generic reader
# (VA 0x61c990 = rva 0x21c990, the one that colours the pings correctly;
# 2026-10-14 18:03 the first version called VA 0xa1c990 by mistake and crashed) writes the int
# straight into [ebp-0x18], the value used when the first read fails.
PATCHES += [
    (0x64A702, bytes.fromhex("8d55d85233c0689c000010568945d88945dcc745e8ffffffffe800d5b3ff"),
     bytes.fromhex("8d55e85233c0689c000010568945d88945dcc745e8ffffffffe87016bdff"),
     "minimap: note team read with the generic property reader (rva 0x64b302)"),
]
# 2026-10-15 00:59: the Q button stays dull (greyed) even when usable. The HUD
# enables a skill button (GM_Skill.RecvNotice_EnableSkillButton, VA 0xa230c0)
# only if none of its disable conditions holds; condition 0x1000003B (VA
# 0xa1d3ad) looks the slot up in a per-slot "available" list that the original
# server's scripts filled and ours never does, so every skill reads disabled.
# That condition now never disables (rank 0 still shows as locked).
PATCHES += [
    (0x61C7E4, bytes.fromhex("b801000000"), bytes.fromhex("31c0909090"),
     "skills: the 'slot available' condition no longer greys the buttons (rva 0x61d3e4)"),
]
# 2026-10-14 23:07: a ping note (category 0x1D) of team 2 gets variant + 2 (the
# enemy's icon set), which the minimap does not draw: the player's red alert
# pings (team 2, for their colour) vanished from it. The + 2 becomes + 0.
PATCHES += [
    (0x64A6FC, bytes.fromhex("83c102"), bytes.fromhex("83c100"),
     "minimap: team-2 ping notes keep their own icon variant (rva 0x64b2fc)"),
]


# 2026-10-16 19:20 (tester: "si intentalo"): the meteor event of Tutorial 1
# (falling rock with its trail, warning, impact explosion, sounds; script
# template 0x1D00019C) is only in pack 0xA000009A, a zone pack (category 0xd)
# like the tutorial's own 0xA000024C, and the client has ONE zone slot: the
# second one never loaded. The pack manager's slots come from the table at
# VA 0x1600a40 (26 entries of {count, category, size KB, size KB, flags},
# built by VA 0x9d3ff0, called from VA 0xa08780); the free-slot finder
# (VA 0x9d3400) already handles any number of slots per category. Category
# 0xd gets 2 slots (155 MB each, committed at start: about 155 MB more RAM).
ZONE_SLOTS_OFFSET = 0x11FEF44
PATCHES += [
    (ZONE_SLOTS_OFFSET, bytes.fromhex("010000000d000000"), bytes.fromhex("020000000d000000"),
     "packs: two zone pack slots (category 0xd) instead of one (VA 0x1600b44)"),
]


def zone_slots(path):
    """Zone pack slots of an exe (1 = original, 2 = patched); 0 if unreadable."""
    try:
        with open(path, "rb") as f:
            f.seek(ZONE_SLOTS_OFFSET)
            raw = f.read(8)
    except OSError:
        return 0
    return int.from_bytes(raw[:4], "little") if len(raw) == 8 and raw[4] == 0xD else 0


def _same(off, cur, new):
    if off == PROP_TABLE and len(cur) == len(new):      # the carriers may differ
        return cur != bytes([0xCC]) * len(cur)
    return cur == new


RSA_DER_OFFSET = 0x11A1F58
RSA_DER_HEADER = bytes.fromhex("30818902818100")
RSA_MODULUS_OFFSET = RSA_DER_OFFSET + len(RSA_DER_HEADER)
RSA_TRAILER = bytes.fromhex("0203010001")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rsa_slot_ok(data):
    return (bytes(data[RSA_DER_OFFSET:RSA_MODULUS_OFFSET]) == RSA_DER_HEADER and
            bytes(data[RSA_MODULUS_OFFSET + 128:RSA_MODULUS_OFFSET + 128 + len(RSA_TRAILER)]) == RSA_TRAILER)


def inspect(path, key=None):
    """Returns a dict: per patch 'original' / 'patched' / 'unknown', the RSA
    slot state and, with a key, whether the embedded modulus is that key's."""
    with open(path, "rb") as f:
        data = f.read()
    out = {"size": len(data), "patches": [], "rsa": "unknown", "key_match": None}
    for off, orig, new, desc in PATCHES:
        cur = data[off:off + len(orig)]
        out["patches"].append((desc, "original" if cur == orig else "patched" if _same(off, cur, new) else "unknown"))
    if _rsa_slot_ok(data):
        out["rsa"] = "found"
        if key is not None:
            out["key_match"] = data[RSA_MODULUS_OFFSET:RSA_MODULUS_OFFSET + 128] == key.n.to_bytes(128, "big")
    return out


def new_key(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(generate_key_pem())


def build(src, dst, key_path, carrier=None):
    """Patch a copy of src into dst. Raises ValueError on an unknown build."""
    data = bytearray(open(src, "rb").read())
    applied = []
    for off, orig, new, desc in PATCHES:
        cur = bytes(data[off:off + len(orig)])
        if _same(off, cur, new):
            applied.append(f"already applied: {desc}")
            continue
        if cur != orig:
            raise ValueError(f"unexpected bytes at {off:#x} ({cur.hex()}): not the 2015 Steam build")
        data[off:off + len(orig)] = new
        applied.append(f"applied: {desc}")
    carriers = [int(c) for c in (carrier or PROP_CARRIERS_DEFAULT)][:6]
    carriers += [PROP_CARRIERS_DEFAULT[0]] * (6 - len(carriers))
    data[PROP_TABLE:PROP_TABLE + 24] = b"".join(c.to_bytes(4, "little") for c in carriers)
    applied.append("props: carriers " + ", ".join(f"{0x4A + i:#x}xxxxxx -> {c:#010x}" for i, c in enumerate(carriers)))
    if not _rsa_slot_ok(data):
        raise ValueError("RSA public key not found at the expected offset: not the 2015 Steam build")
    key = load_key(key_path)
    if key.e != 65537 or key.bits != 1024:
        raise ValueError("the server key must be RSA-1024 with e = 65537")
    data[RSA_MODULUS_OFFSET:RSA_MODULUS_OFFSET + 128] = key.n.to_bytes(128, "big")
    applied.append("applied: RSA login key = modulus of the server key")
    tmp = dst + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, dst)
    return applied
