"""Skill structures for the Stolen Power slots (D = slot 7, F = slot 8).

The client reads the skill of a slot from a champion property (table at VA
0x15EDA28: slot 7 = 0x100008F0, slot 8 = 0x100008F1). That property is not a
DID but a property collection (value kind 0x0B) holding the skill's whole
definition: name, icon, texts, stats, behaviour (0x10000328 = the skill's
script DID), ... For Q-R it comes with the champion's own record; a Stolen
Power has to be sent by the server.

The definition is built from the game's own data, read from the player's
install at run time (nothing is shipped):

  - the Stolen Powers catalog (record 0x480003CD) lists each power's base skill
    and its champion versions; the slot collection is the base skill's
    0x1000003F collection with the version's 0x1000003F entries on top;
  - the network carries no value kinds, so every property's kind comes from
    the client's own property descriptors, dumped by `tools\\diag.py --props`
    to logs\\props.txt (id at +8, kind at +0xC of each descriptor).

Pack record format (as read here): u32 did | u32 0 | u32 count | entries;
entry = u32 key | u32 type word (= key; key | 0x40000000 = no value) | value;
array (0x0C) = u32 count | elements (u32 element key | value); collection
(0x0B) = u32 0 | u32 count | entries; string (0x0E) = u32 mode 0 | u32 token |
u32 table | u32 0 | u32 0; IID (7) 8 bytes; everything else 4 bytes.
"""
import os
import struct

from . import log

KIND_ENUM, KIND_F32, KIND_ENUM2, KIND_TABLE, KIND_ARRAY, KIND_STRING = 8, 9, 0x0A, 0x0B, 0x0C, 0x0E
KIND_INT, KIND_U32, KIND_DID, KIND_BOOL, KIND_IID = 0x10, 0x13, 0x15, 0x16, 7
# kinds the server can re-encode for the wire; entries of any other kind are left out
SUPPORTED = {KIND_ENUM, KIND_F32, KIND_ENUM2, KIND_TABLE, KIND_ARRAY, KIND_STRING, KIND_INT, KIND_U32,
             KIND_DID, KIND_BOOL}
SKILL_BLOCK = 0x1000003F
CATALOG = 0x480003CD
STOLEN_PACK = 0xA00000B3
# Gaslight Batman's surveillance camera and Superman's Super Strength
CAMERA_VERSION, SUPER_STRENGTH_VERSION = 0x48000808, 0x48000A3B

# 2026-10-16: the value kinds of every property that the Stolen Powers catalog
# and its 65 skills use (from the client's own descriptors, diag --props), so
# D and F work without logs/props.txt (it disappeared when logs/ was cleared).
# A props.txt, when present, is read on top of these.
BUILTIN_KINDS = {
    0x1000003d: 0x08,
    0x1000003e: 0x0e,
    0x1000003f: 0x0b,
    0x100000e6: 0x08,
    0x100001c0: 0x0e,
    0x100002a3: 0x15,
    0x10000302: 0x15,
    0x10000328: 0x15,
    0x10000448: 0x13,
    0x100004ae: 0x0e,
    0x100004af: 0x0b,
    0x100004b0: 0x0e,
    0x100004b3: 0x0b,
    0x100004b4: 0x0c,
    0x100004b6: 0x08,
    0x100004b7: 0x09,
    0x100004b9: 0x0e,
    0x100004d1: 0x0e,
    0x100004d2: 0x09,
    0x100004d3: 0x0b,
    0x100004d4: 0x0b,
    0x100004d7: 0x15,
    0x10000534: 0x10,
    0x10000535: 0x16,
    0x10000620: 0x15,
    0x10000645: 0x08,
    0x10000646: 0x08,
    0x1000068d: 0x13,
    0x100006d7: 0x15,
    0x100006d8: 0x15,
    0x100006df: 0x13,
    0x10000708: 0x16,
    0x10000729: 0x0e,
    0x100007a6: 0x13,
    0x100007a7: 0x16,
    0x1000083d: 0x08,
    0x10000840: 0x15,
    0x10000841: 0x0c,
    0x10000842: 0x0c,
    0x10000850: 0x15,
    0x10000853: 0x08,
    0x10000854: 0x0b,
    0x10000855: 0x0c,
    0x10000920: 0x0e,
    0x10000922: 0x0b,
    0x10000abc: 0x08,
    0x10000d32: 0x16,
    0x10000d9e: 0x16,
}

_kinds = None
_cache = {}


def catalog_kinds():
    """{property id: kind code} from catalog/data/properties.tsv ({} if it is missing)."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "catalog", "data",
                        "properties.tsv")
    out = {}
    try:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                parts = ln.rstrip("\n").split("\t")
                if len(parts) >= 3 and parts[0].startswith("0x") and parts[2].startswith("0x"):
                    out[int(parts[0], 16)] = int(parts[2], 16)
    except (OSError, ValueError):
        return {}
    return out


def load_kinds(path):
    """{property id: kind} from tools\\diag.py --props's props.txt."""
    kinds = {}
    with open(path) as f:
        for ln in f:
            if ln.startswith("#"):
                continue
            parts = ln.split()
            if len(parts) < 2 or len(parts[1]) < 32:
                continue
            raw = bytes.fromhex(parts[1])
            kinds[int(parts[0], 16)] = struct.unpack_from("<I", raw, 12)[0]
    return kinds


class _Reader:
    def __init__(self, data, pos, kinds):
        self.d, self.p, self.kinds = data, pos, kinds

    def u32(self):
        v = struct.unpack_from("<I", self.d, self.p)[0]
        self.p += 4
        return v

    def value(self, key):
        kind = self.kinds.get(key)
        if kind is None:
            raise ValueError(f"no kind known for property {key:#x}")
        if kind == KIND_TABLE:
            self.u32()
            return kind, [e for e in (self.entry() for _ in range(self.u32())) if e]
        if kind == KIND_ARRAY:
            out = []
            for _ in range(self.u32()):
                ekey = self.u32()
                ekind, evalue = self.value(ekey)
                out.append((ekey, ekind, evalue))
            return kind, out
        if kind == KIND_STRING:
            _, token, table, _, _ = (self.u32() for _ in range(5))
            return kind, (token, table)
        if kind == KIND_IID:
            lo, hi = self.u32(), self.u32()
            return kind, lo | hi << 32
        return kind, self.u32()

    def entry(self):
        key, word = self.u32(), self.u32()
        if word == key | 0x40000000:
            return None                                   # present without a value
        kind, value = self.value(key)
        return key, kind, value


def read_record(data, did, kinds):
    """The top-level entries of record `did` in a pack's data, or None."""
    pat = struct.pack("<II", did, 0)
    k = data.find(pat)
    while k >= 0:
        try:
            r = _Reader(data, k + 8, kinds)
            n = r.u32()
            if 0 < n < 64:
                return [e for e in (r.entry() for _ in range(n)) if e]
        except (ValueError, struct.error):
            pass
        k = data.find(pat, k + 1)
    return None


def _clean(entries, dropped):
    out = []
    for key, kind, value in entries:
        if kind not in SUPPORTED:
            dropped.append(f"{key:#x} (kind {kind:#x})")
            continue
        if kind == KIND_TABLE:
            value = _clean(value, dropped)
        elif kind == KIND_ARRAY:
            value = _clean(value, dropped)
        out.append((key, kind, value))
    return out


def _block(entries):
    for key, kind, value in entries or ():
        if key == SKILL_BLOCK and kind == KIND_TABLE:
            return value
    return None


def base_of(data, version, kinds):
    """The base skill of a Stolen Power version: the first skill of its
    catalog group."""
    cat = read_record(data, CATALOG, kinds) or []
    for key, kind, groups in cat:
        if kind != KIND_ARRAY:
            continue
        for _, _, members in groups:
            dids = [v for _, _, v in members]
            if version in dids:
                return dids[0]
    return None


def stolen_power(cfg, version):
    """The slot collection (list of (key, kind, value)) for a Stolen Power
    version, or None (no props.txt, pack not found, ...)."""
    global _kinds
    if version in _cache:
        return _cache[version]
    result = None
    try:
        if _kinds is None:
            path = cfg["tutorial"].get("props_file") or os.path.join(cfg.log_dir, "props.txt")
            _kinds = dict(BUILTIN_KINDS)
            # 2026-10-17 22:51 (tester: no throw rings): the throw skill 0x480003C9 read as 0 properties (its
            # 0x10000ABC / 0x1000063A / 0x100006D5 / ... had no known kind), so F kept the lift skill while
            # carrying. The catalog's property kinds fill the gaps (props.txt still wins).
            _kinds.update({k: v for k, v in catalog_kinds().items() if k not in _kinds})
            if os.path.isfile(path):
                _kinds.update(load_kinds(path))
        if _kinds:
            from . import rp
            pack = rp.PackSet(os.path.join(cfg.game_dir, "rp")).pack(STOLEN_PACK)
            base = base_of(pack.data, version, _kinds)
            merged = {}
            order = []
            for did in ([base] if base and base != version else []) + [version]:
                for key, kind, value in _block(read_record(pack.data, did, _kinds)) or ():
                    if key not in merged:
                        order.append(key)
                    merged[key] = (key, kind, value)
            dropped = []
            result = _clean([merged[k] for k in order], dropped) or None
            log.info(f"stolen power {version:#x} (base {base or 0:#x}): {len(result or [])} properties"
                     + (f", left out: {', '.join(dropped)}" if dropped else ""))
    except (OSError, ValueError, struct.error) as e:
        log.info(f"stolen power {version:#x}: {e}")
        result = None
    _cache[version] = result
    return result


TARGETING_PROPERTY = 0x1000003D     # a skill's targeting type (1 = ground position, 14 = an entity)


def with_targeting(table, value):
    """The collection with its top-level targeting type replaced."""
    return [(k, kind, value if k == TARGETING_PROPERTY else v) for k, kind, v in table]


def slot_table(cfg, slot, version):
    """stolen_power() for a HUD slot, with the server's per-slot adjustments:
    2026-10-16 (static analysis) Super Strength (F) targets an entity (type 14)
    and the client's picker refuses our car, so F sent nothing: on slot 8 it is
    a ground-target skill like the camera ([tutorial] strength_targeting; 0 =
    keep), so F + click sends the position."""
    table = stolen_power(cfg, version)
    if table and slot == 8:
        t = int(cfg["tutorial"].get("strength_targeting", 1) or 0)
        if t:
            table = with_targeting(table, t)
    return table
