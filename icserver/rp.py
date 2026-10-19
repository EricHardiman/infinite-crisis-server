"""Reader for Turbine "10PR" resource packs (rp\\*.rp).

Format as documented by the original project's tools/rplib.py: header at 0
(u32 payload size at 0xC, u32 record count at 0x10); payload from 0x400 in
0x20000-byte blocks whose last 4 bytes are a trailer; payload = count x u32
DIDs followed by one zlib stream with all records concatenated.

Records carry no size table. Instead of guessing where a record ends, this
module answers the questions the server needs ("where is this DID's record
with this header?", "which records reference that DID?") directly on the
decompressed stream.
"""
import bisect
import os
import re
import struct
import zlib


class Pack:
    def __init__(self, path):
        self.path = path
        self.name = os.path.basename(path).lower()
        with open(path, "rb") as f:
            d = f.read()
        if d[:4] != b"10PR":
            raise ValueError(f"{path}: not a 10PR pack")
        size, count = struct.unpack_from("<II", d, 0xC)
        raw = bytearray()
        p, end = 0x400, 0x400 + size
        while p < end:
            raw += d[p:min(p + 0x1FFFC, end)]
            p += 0x20000
        self.ids = list(struct.unpack_from("<%dI" % count, raw, 0))
        self.data = zlib.decompress(bytes(raw[4 * count:]))

    def find_all(self, did, header=b""):
        """Offsets where the u32 DID is followed by the given header bytes."""
        pat = struct.pack("<I", did) + header
        out, k = [], self.data.find(pat)
        while k >= 0:
            out.append(k)
            k = self.data.find(pat, k + 1)
        return out

    def record_starts(self):
        """Best-effort record starts (DID in list order), sorted by offset."""
        starts, pos = [], 0
        for did in self.ids:
            k = self.data.find(struct.pack("<I", did), pos)
            if k < 0:
                k = self.data.find(struct.pack("<I", did))
            if k >= 0:
                starts.append((k, did))
                pos = k + 4
        starts.sort()
        return starts


class PackSet:
    """Lazy access to the game's rp folder (only the packs that are asked for)."""

    def __init__(self, rp_dir):
        self.rp_dir = rp_dir
        self._cache = {}

    def pack(self, pack_id):
        name = f"0x{pack_id:08x}.rp" if isinstance(pack_id, int) else pack_id
        if name not in self._cache:
            self._cache[name] = Pack(os.path.join(self.rp_dir, name))
        return self._cache[name]


# ---- encounter layouts ---------------------------------------------------------------

_ENTRY = re.compile(rb"([\x03-\x40])\x00\x00\x00([0-9A-Za-z_]{3,64})\x00{0,3}(...\x2e)", re.S)
# lookahead so that overlapping candidates are all tried
_POS = re.compile(rb"(?=([\x00-\xff])\x00\x00\x00([\x00-\xff])\x00\x00\x00([\x00-\xff])\x00\x00\x00(.{12})(.{16}))", re.S)


def _positions(seg):
    """Position structs: u32 cell | u32 landblock x | u32 landblock y | f32 x,y,z |
    quaternion (w, x, y, z). Accepted only when the quaternion is normalised."""
    out = []
    for m in _POS.finditer(seg):
        x, y, z = struct.unpack("<fff", m.group(4))
        q = struct.unpack("<4f", m.group(5))
        norm = sum(v * v for v in q)
        if 0.98 < norm < 1.02 and all(abs(v) < 4000 for v in (x, y, z)) and abs(z) > 1:
            out.append({"cell": m.group(1)[0], "lb": (m.group(2)[0], m.group(3)[0]),
                        "xyz": (x, y, z), "quat": q})
    return out


def layout_entries(pack, max_span=4096):
    """Named placements: u32 name length | name (padded to 4) | u32 world-state
    DID (0x2e...), followed by properties and position structs. Found in the
    encounter layout records (DID prefix 0x1d) and in cinematics (0x35).
    Returns [{record, name, wstate, positions}]; positions[0] is the spawn
    point, further ones a patrol path. 'record' is the enclosing record as
    far as the pack's record list can tell."""
    starts = pack.record_starts()
    offs = [o for o, _ in starts]
    found = [(m.start(), m.group(2).decode(), struct.unpack("<I", m.group(3))[0])
             for m in _ENTRY.finditer(pack.data) if len(m.group(2)) == m.group(1)[0]]
    entries = []
    for j, (pos, name, ws) in enumerate(found):
        stop = min(found[j + 1][0] if j + 1 < len(found) else len(pack.data), pos + max_span)
        i = bisect.bisect_right(offs, pos) - 1
        record = starts[i][1] if i >= 0 else 0
        entries.append({"record": record, "name": name, "wstate": ws,
                        "positions": _positions(pack.data[pos:stop])})
    return entries


def variants_for_wstates(pack):
    """{world state DID: character variant DID}: a variant 0x40xxxxxx has a
    twin 0x49xxxxxx (same low bits) whose properties name its world state."""
    out = {}
    twins = [d for d in pack.ids if d >> 24 == 0x49]
    for twin in twins:
        for k in pack.find_all(twin):
            head = pack.data[k + 4:k + 8]
            if head not in (b"\x03\x00\x00\x00", b"\x04\x00\x00\x00", b"\x00\x00\x00\x00"):
                continue
            seg = pack.data[k:k + 4000]
            for j in range(8, len(seg) - 4, 4):
                v = struct.unpack_from("<I", seg, j)[0]
                if v >> 24 == 0x2E and v & 0xFFFFFF < 0x100000:
                    out.setdefault(v, 0x40000000 | (twin & 0xFFFFFF))
                    break
            break
    return out


ENTITY_WSTATE_PROP = 0x510   # property of an entity twin (0x49...) naming its world state


def entity_classes_for(pack, wstates):
    """{world state: entity class 0x40xxxxxx} for the given world states.

    A placeable object (a door, a destructible vehicle, a character) is an
    entity 0x40xxxxxx whose twin 0x49xxxxxx has property 0x510 = its world
    state 0x2e... (e.g. Door 0x49000b0f -> 0x2e0010f3). Creating the bare world
    state builds an object without the entity's model, so it is invisible."""
    twins = sorted(d for d in pack.ids if d >> 24 == 0x49)
    twin_set = set(twins)
    out = {}
    for ws in wstates:
        pat = struct.pack("<III", ENTITY_WSTATE_PROP, ENTITY_WSTATE_PROP, ws)
        k = pack.data.find(pat)
        while k >= 0 and ws not in out:
            # owner: the nearest preceding twin DID (records are a few KB at most)
            lo = max(0, k - 8000)
            j = k - 4
            while j >= lo:
                if pack.data[j + 3] == 0x49:
                    v = struct.unpack_from("<I", pack.data, j)[0]
                    if v in twin_set and pack.data[j + 4:j + 8] in (b"\0\0\0\0", b"\x03\0\0\0", b"\x04\0\0\0"):
                        out[ws] = 0x40000000 | (v & 0xFFFFFF)
                        break
                j -= 1
            k = pack.data.find(pat, k + 1)
    return out
