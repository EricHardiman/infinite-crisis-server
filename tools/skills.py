"""Readable dump of a champion's skills (step 2 of the Batman plan).

Usage:
    python tools\\skills.py                       (Gaslight Batman)
    python tools\\skills.py "Gaslight Batman"
    python tools\\skills.py 0x48000615            (one specific record)

What it does:
1. Reads the English string tables from every pack (token -> text).
2. Finds the 0x48 records that name the champion (by its name token) and the
   0x48 records those point to (one level). That is where its skill sheets
   live (in pack 0xA0000122, 0x48000615 holds Echoes, Bat Scream, Sonic
   Batarang, Sonic Shell and Bat Flight with their numbers).
3. Walks each record as a property tree: "key, key|type, value".
   Strings (token + 0x2B table) are resolved; numbers are shown both as
   integer and as float. The game's property names are not known yet: they
   will be identified by comparing with what is seen in the game.

Writes logs\\skills.txt (it does not copy game files, only numbers and short
strings for study).
"""
import os
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from icserver import config as cfgmod  # noqa: E402
from icserver import rp  # noqa: E402


def tail_tables(path):
    """String tables (zlib) stored after the pack contents."""
    with open(path, "rb") as f:
        d = f.read()
    size = struct.unpack_from("<I", d, 0xC)[0]
    off = (0x400 + size + 4 * (size // 0x1FFFC) + 0x3FF) & ~0x3FF
    out = []
    while off < len(d):
        if d[off:off + 2] == b"\x78\x01":
            try:
                o = zlib.decompressobj()
                data = o.decompress(d[off:])
                used = len(d) - off - len(o.unused_data)
                out.append(data)
                off = (off + used + 0x3FF) & ~0x3FF
                continue
            except zlib.error:
                pass
        off += 0x400
    return out


def _printable(raw):
    try:
        text = raw.decode("utf-16le")
    except UnicodeDecodeError:
        return None
    return text if text and all(c.isprintable() or c in "\n\r\t" for c in text) else None


def parse_table(tbl):
    """Entries "token | nparts | per part: u32 len + utf16" are found by scanning
    (the data between entries is not fully understood)."""
    did, lang, _count = struct.unpack_from("<III", tbl, 0)
    res, p, end = {}, 12, len(tbl) - 12
    while p < end:
        token, nparts, n = struct.unpack_from("<III", tbl, p)
        if 1 <= nparts <= 16 and 1 <= n <= 6000 and token > 0xFFFF:
            q, parts, ok = p + 8, [], True
            for _ in range(nparts):
                if q + 4 > len(tbl):
                    ok = False
                    break
                m = struct.unpack_from("<I", tbl, q)[0]
                text = _printable(tbl[q + 4:q + 4 + 2 * m]) if 0 < m <= 6000 else None
                if text is None:
                    ok = False
                    break
                parts.append(text)
                q += 4 + 2 * m
            if ok:
                res.setdefault(token, "{}".join(parts))
                p = q
                continue
        p += 2
    return did, lang, res


def load_strings(rp_dir, names):
    strings = {}
    for i, name in enumerate(names, 1):
        print(f"\r[strings {i}/{len(names)}] {name}      ", end="", flush=True)
        try:
            for t in tail_tables(os.path.join(rp_dir, name)):
                try:
                    did, lang, res = parse_table(t)
                except struct.error:
                    continue
                if did >> 24 != 0x2B:
                    continue
                for tok, s in res.items():
                    tok = (did, tok)                     # tokens repeat across tables
                    old = strings.get(tok)
                    # several languages share tokens: keep the English (plain ASCII) one
                    if old is None or (not old.isascii() and s.isascii()):
                        strings[tok] = s
        except OSError:
            continue
    print()
    return strings


def f32(v):
    return struct.unpack("<f", struct.pack("<I", v))[0]


def describe(body, strings):
    """The record as a list of readable lines."""
    n = len(body) // 4
    w = struct.unpack_from("<%dI" % n, body)
    out, i = [], 2
    while i < n:
        k = w[i]
        if k >> 24 == 0x10 and i + 2 < n and (w[i + 1] & 0x0FFFFFFF) == (k & 0x0FFFFFFF):
            kind, v = w[i + 1] >> 28, w[i + 2]
            text = ""
            if i + 3 < n and w[i + 3] >> 24 == 0x2B:
                text = f'  text "{strings.get((w[i + 3], v), "?")}"'
            elif v >> 24 in (0x10, 0x13, 0x1D, 0x1E, 0x2E, 0x34, 0x35, 0x3A, 0x3B, 0x40, 0x48, 0x49):
                text = f"  (DID {v:#010x})"
            elif 0x30000000 <= v <= 0x4F000000 or 0xB0000000 <= v <= 0xCF000000:
                text = f"  = {f32(v):g}"
            out.append(f"  {i * 4:05x}  prop {k:#010x} type {kind:x}  value {v:#010x} ({v}){text}")
            i += 3
            continue
        if i + 1 < n and w[i + 1] >> 24 == 0x2B and (w[i + 1], k) in strings:
            out.append(f'  {i * 4:05x}  ===== "{strings[(w[i + 1], k)]}" =====')
            i += 2
            continue
        out.append(f"  {i * 4:05x}  {k:#010x}")
        i += 1
    return out


def main():
    cfg = cfgmod.load()
    rp_dir = os.path.join(cfg.game_dir, "rp")
    names = sorted(f for f in os.listdir(rp_dir) if f.lower().endswith(".rp"))
    arg = sys.argv[1] if len(sys.argv) > 1 else "Gaslight Batman"
    strings = load_strings(rp_dir, names)
    wanted = set()
    if arg.lower().startswith("0x"):
        wanted.add(int(arg, 16))
    else:
        toks = {t for (_tbl, t), s in strings.items() if s.strip().lower() == arg.lower()}
        print(f"'{arg}': {len(toks)} text tokens")
        if arg.lower() == "gaslight batman":
            wanted |= {0x48000615, 0x48000617}     # known: skill set (0xA0000122) and champion
        pats = [struct.pack("<I", t) for t in toks]
        for i, name in enumerate(names, 1):
            print(f"\r[champion {i}/{len(names)}] {name}      ", end="", flush=True)
            try:
                pack = rp.Pack(os.path.join(rp_dir, name))
            except (OSError, ValueError):
                continue
            starts = None
            for pat in pats:
                k = pack.data.find(pat)
                while k >= 0:
                    if starts is None:
                        starts = pack.record_starts()
                        offs = [o for o, _ in starts]
                    import bisect
                    j = bisect.bisect_right(offs, k) - 1
                    if j >= 0 and starts[j][1] >> 24 == 0x48:
                        wanted.add(starts[j][1])
                    k = pack.data.find(pat, k + 1)
        print()
    lines, done = [], set()
    for depth in range(2):
        nxt = set()
        for i, name in enumerate(names, 1):
            todo = wanted - done
            if not todo:
                break
            print(f"\r[records {depth + 1}] {i}/{len(names)} {name}      ", end="", flush=True)
            try:
                pack = rp.Pack(os.path.join(rp_dir, name))
            except (OSError, ValueError):
                continue
            ids = set(pack.ids)
            hit = [d for d in todo if d in ids]
            if not hit:
                continue
            starts = pack.record_starts()
            # records have no size table and the next-DID guess often cuts them
            # short: a 0x48 record runs to the next 0x48 record (at most 40 KB)
            same = [o for o, did in starts if did >> 24 == 0x48
                    and pack.data[o + 4:o + 8] == bytes(4)]     # a real 0x48 header, not a reference
            offs = {}
            for o, did in starts:
                stop = next((x for x in same if x > o), len(pack.data))
                offs[did] = (o, min(stop, o + 40000))
            for d in hit:
                if d not in offs:
                    continue
                a, b = offs[d]
                body = pack.data[a:min(b, a + 400000)]
                done.add(d)
                lines.append(f"\n######## record {d:#010x} in {name} ({b - a} bytes)")
                lines += describe(body, strings)
                if depth == 0:
                    for q in range(0, len(body) - 3, 4):
                        v = struct.unpack_from("<I", body, q)[0]
                        if v >> 24 == 0x48 and v != d:
                            nxt.add(v)
        print()
        wanted |= nxt
    out = os.path.join(cfg.log_dir, "skills.txt")
    os.makedirs(cfg.log_dir, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"Skills: {arg} ({len(done)} records)\n" + "\n".join(lines) + "\n")
    print(f"Saved to {out}")


if __name__ == "__main__":
    main()
