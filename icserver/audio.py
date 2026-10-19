"""The game's sounds (Wwise), read from the player's install for the catalog.

2026-10-16 17:47 (tester): "the meteors make a sound when they fall; do you
have all the sound data in a dictionary?"

Where the sounds are
  audio\\Audio_SB.pck       AKPK package: 41 sound banks (BKHD / DIDX / DATA /
                            HIRC / STID); English(US)\\Audio_SB.pck etc. hold
                            the voices; *_Str.pck the streamed files.
  rp packs, records 0x52    "this map / champion uses bank X":
                            u32 did | u32 bank id | u32 n | n bytes name. The
                            bank id is Wwise's FNV-1 hash of the lower-case
                            name (checked: "Destruction" = 0x91D0BEA7).
  any record                a sound event is a typed value of kind 0x2C:
                            ... | u32 0x2C | u32 event id.

Event names are not in the data (only their hashes), so the catalog lists
events by id, bank and the records that play them.
"""
import collections
import os
import re
import struct

KIND_SOUND_EVENT = 0x2C
HIRC_EVENT, HIRC_ACTION, HIRC_SOUND = 4, 3, 2


def fnv(name):
    """Wwise short id of a name."""
    h = 2166136261
    for c in name.lower().encode():
        h = (h * 16777619) & 0xFFFFFFFF
        h ^= c
    return h


def banks(pck_path):
    """{bank id: bank bytes} of an AKPK package."""
    with open(pck_path, "rb") as f:
        d = f.read()
    if d[:4] != b"AKPK":
        raise ValueError(f"{pck_path}: not an AKPK package")
    _hs, _ver, lang_sz, _bank_sz, _str_sz, _ext_sz = struct.unpack_from("<6I", d, 4)
    p = 28 + lang_sz
    n = struct.unpack_from("<I", d, p)[0]
    out = {}
    for i in range(n):
        bid, blk, size, off, _lang = struct.unpack_from("<5I", d, p + 4 + 20 * i)
        out[bid] = d[off * blk:off * blk + size]
    return out


def _sections(b):
    q, out = 0, {}
    while q + 8 <= len(b):
        tag, size = b[q:q + 4], struct.unpack_from("<I", b, q + 4)[0]
        out[tag] = (q + 8, size)
        q += 8 + size
    return out


def events(pck_path):
    """{event id: {"bank": bank id, "actions": n, "sounds": n of the bank}}."""
    out = {}
    for bid, b in banks(pck_path).items():
        secs = _sections(b)
        if b"HIRC" not in secs:
            continue
        s0, _size = secs[b"HIRC"]
        cnt, r = struct.unpack_from("<I", b, s0)[0], s0 + 4
        found, sounds = [], 0
        for _ in range(cnt):
            t = b[r]
            osz, oid = struct.unpack_from("<II", b, r + 1)
            if t == HIRC_EVENT:
                found.append((oid, struct.unpack_from("<I", b, r + 9)[0]))
            elif t == HIRC_SOUND:
                sounds += 1
            r += 5 + osz
        for oid, n in found:
            out[oid] = {"bank": bid, "actions": n, "bank_sounds": sounds}
    return out


def scan_packs(rp_dir, event_ids, log=print):
    """Bank names (records 0x52) and which records play which events."""
    from . import rp
    names, users = {}, collections.defaultdict(set)
    pat = re.compile(rb"\x2c\x00\x00\x00(....)", re.S)
    for fn in sorted(f for f in os.listdir(rp_dir) if f.lower().endswith(".rp")):
        try:
            pk = rp.Pack(os.path.join(rp_dir, fn))
        except (OSError, ValueError):
            continue
        starts = pk.record_starts()
        offs = [s[0] for s in starts]
        import bisect
        for o, did in starts:
            if did >> 24 == 0x52:
                h, n = struct.unpack_from("<II", pk.data, o + 4)
                if 0 < n < 80:
                    names[h] = pk.data[o + 12:o + 12 + n].decode("ascii", "replace")
        for m in pat.finditer(pk.data):
            v = struct.unpack("<I", m.group(1))[0]
            if v in event_ids:
                i = bisect.bisect_right(offs, m.start()) - 1
                if i >= 0:
                    users[v].add(starts[i][1])
        log(f"  {fn}")
    return names, users
