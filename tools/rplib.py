"""Reader for Turbine "10PR" resource packs (rp/*.rp).

Layout: header at 0 ("10PR", u32 version, u32 1, u32 payload size, u32 record
count, ...). Payload starts at 0x400 and is stored in 0x20000-byte file blocks
whose last 4 bytes are a block trailer (not payload). Payload = count * u32
data ids (DIDs) followed by ONE zlib stream holding all records concatenated
in the same order. Each record begins with its own DID; there is no size
table, so records are split by searching for the next DID (heuristic).
"""
import glob, os, struct, zlib

RP_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "rp"))


def load_pack(path):
    d = open(path, "rb").read()
    size, count = struct.unpack_from("<II", d, 0xC)
    raw = bytearray()
    p, end = 0x400, 0x400 + size
    while p < end:
        raw += d[p:min(p + 0x1FFFC, end)]
        p += 0x20000
    ids = struct.unpack_from("<%dI" % count, raw, 0)
    return ids, zlib.decompress(bytes(raw[4 * count:]))


def split_records(ids, data):
    """Yield (did, offset, bytes). Records are located by searching for each
    DID: in list order when that works, else by first occurrence anywhere
    (records are not always stored in DID-list order). Heuristic: a DID that
    is referenced by an earlier record can produce a wrong split."""
    starts = []
    pos = 0
    for did in ids:
        k = data.find(struct.pack("<I", did), pos)
        if k < 0:
            starts = None
            break
        starts.append((did, k))
        pos = k + 4
    if starts is None:
        starts = []
        for did in ids:
            k = data.find(struct.pack("<I", did))
            if k >= 0:
                starts.append((did, k))
        starts.sort(key=lambda t: t[1])
    for i, (did, k) in enumerate(starts):
        end = starts[i + 1][1] if i + 1 < len(starts) else len(data)
        yield did, k, data[k:end]


def packs():
    return sorted(glob.glob(os.path.join(RP_DIR, "*.rp")))
