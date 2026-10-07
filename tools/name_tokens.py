"""Brute-force: find every (token, 1, len, utf16 text) string entry in the raw
tail region of each pack (the per-language string tables after the payload; they
are zlib streams made of stored blocks, so the text is visible in the raw file).
Writes strings_all.tsv: pack, file offset, token, text. All 4 languages are included."""
import os, re, struct
import rplib
out = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "strings_all.tsv"), "w", encoding="utf-8")
n = 0
pat = re.compile(rb"(....)\x01\x00\x00\x00(..)\x00\x00", re.S)
for path in rplib.packs():
    d = open(path, "rb").read()
    size = struct.unpack_from("<I", d, 0xC)[0]
    start = 0x400 + size
    for m in pat.finditer(d, start):
        ln = struct.unpack("<H", m.group(2))[0]
        p = m.end()
        if not (0 < ln < 4000) or p + 2 * ln > len(d): continue
        raw = d[p:p + 2 * ln]
        try: s = raw.decode("utf-16le")
        except UnicodeDecodeError: continue
        if all(c.isprintable() or c in "\n\r\t" for c in s):
            out.write("%s\t%x\t%08x\t%s\n" % (os.path.basename(path), m.start(), struct.unpack("<I", m.group(1))[0],
                                              s.replace("\n", "\n").replace("\t", " ").replace("\r", "")))
            n += 1
out.close(); print("strings", n)
