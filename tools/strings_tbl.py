"""Parse the localized string tables stored after each pack's payload.
Table: u32 did (prefix 0x2b) | u32 language? | u32 count | entries:
  u32 token | u32 nparts | per part: u32 len | utf16[len] ... (heuristic)
Writes strings_en.tsv: table did, token, text (first language table of each pack = English)."""
import os, struct, zlib, sys
import rplib

def tail_tables(path):
    d = open(path, "rb").read()
    size = struct.unpack_from("<I", d, 0xC)[0]
    nblocks = -(-size // 0x1FFFC)
    off = 0x400 + nblocks * 0x20000 if size else 0x400
    off = min(off, (0x400 + size + 4 * (size // 0x1FFFC) + 0x3FF) & ~0x3FF)
    out = []
    while off < len(d):
        if d[off:off + 2] == b"\x78\x01":
            try:
                o = zlib.decompressobj(); data = o.decompress(d[off:])
                used = len(d) - off - len(o.unused_data)
                out.append(data); off = (off + used + 0x3FF) & ~0x3FF; continue
            except zlib.error:
                pass
        off += 0x400
    return out

def parse(tbl):
    did, lang, count = struct.unpack_from("<III", tbl, 0)
    p = 12; res = []
    for _ in range(count):
        if p + 12 > len(tbl): break
        token, nparts = struct.unpack_from("<II", tbl, p); p += 8
        parts = []
        for _ in range(nparts):
            n = struct.unpack_from("<I", tbl, p)[0]; p += 4
            parts.append(tbl[p:p + 2 * n].decode("utf-16le", "replace")); p += 2 * n
        res.append((token, "".join(parts)))
        # trailing per-entry data is unknown; resync heuristically handled by caller
    return did, lang, count, res, p

if __name__ == "__main__":
    path = os.path.join(rplib.RP_DIR, "0xa0000116.rp")
    for t in tail_tables(path):
        did, lang, count, res, p = parse(t)
        print(hex(did), lang, count, len(t), "parsed", len(res), "consumed", p)
        for tok, s in res[:5]: print("   %08x %r" % (tok, s[:70]))
        print("   raw:", t[:96].hex())
