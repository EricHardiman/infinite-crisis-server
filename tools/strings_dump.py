"""Dump English localized strings from all packs to strings_en.tsv (table did, token, text).
Entry layout (heuristic): u32 token | u32 nparts | (u32 len | utf16 text) | trailing bytes (usually 6 zero bytes)."""
import os, struct
import rplib, strings_tbl

def entries(t):
    did, lang, count = struct.unpack_from("<III", t, 0)
    p = 12; out = []
    while p + 12 <= len(t) and len(out) < count:
        tok, nparts, n = struct.unpack_from("<III", t, p)
        if nparts == 1 and n < 20000 and p + 12 + 2 * n <= len(t):
            out.append((tok, t[p + 12:p + 12 + 2 * n].decode("utf-16le", "replace")))
            p += 12 + 2 * n + 6
            # resync if the trailer was longer than 6 bytes
            for k in range(p, min(p + 64, len(t) - 12)):
                a, b, c = struct.unpack_from("<III", t, k)
                if b == 1 and c < 20000 and k + 12 + 2 * c <= len(t):
                    p = k; break
        else:
            p += 1
    return did, out

seen = set(); n = 0
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "strings_en.tsv"), "w", encoding="utf-8") as f:
    for path in rplib.packs():
        tabs = strings_tbl.tail_tables(path)
        if not tabs: continue
        did, ents = entries(tabs[0])
        for tok, s in ents:
            if (did, tok) in seen: continue
            seen.add((did, tok)); n += 1
            f.write("%08x\t%08x\t%s\n" % (did, tok, s.replace("\n", "\n").replace("\t", " ")))
print("strings", n)
