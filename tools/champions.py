"""Enumerate game-data records (DID prefix 0x48) by their 'parent' property 0x1000048b
and resolve their name property 0x10000433 (string token) to English text.
Record: u32 did | u32 0 | u32 nprops | props {u32 id, u32 id, value...}; first prop is
0x1000048b -> parent DID; name prop = 0x10000433,0x10000433,0,token,0x2b000005.
Writes gamedata_48.tsv: did, parent, nprops, name."""
import os, re, struct, collections
import rplib
tok2name = {}
for l in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "strings_all.tsv"), encoding="utf-8", errors="replace"):
    p = l.rstrip("\n").split("\t", 3)
    if len(p) == 4: tok2name.setdefault(int(p[2], 16), p[3])
pat = re.compile(rb"(...\x48)\x00\x00\x00\x00(.)\x00\x00\x00\x8b\x04\x00\x10\x8b\x04\x00\x10(....)", re.S)
recs = {}
for path in rplib.packs():
    ids, data = rplib.load_pack(path)
    for m in pat.finditer(data):
        did = struct.unpack("<I", m.group(1))[0]; n = m.group(2)[0]; parent = struct.unpack("<I", m.group(3))[0]
        seg = data[m.end():m.end() + 400]
        k = seg.find(bytes.fromhex("3304001033040010"))
        name = None
        if k >= 0:
            tok = struct.unpack_from("<I", seg, k + 12)[0]; name = tok2name.get(tok, "tok_%08x" % tok)
        if did not in recs: recs[did] = (parent, n, name, os.path.basename(path))
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "gamedata_48.tsv"), "w", encoding="utf-8") as f:
    for did in sorted(recs):
        parent, n, name, pk = recs[did]
        f.write("%08x\t%08x\t%d\t%s\t%s\n" % (did, parent, n, name, pk))
c = collections.Counter(v[0] for v in recs.values())
print("records", len(recs)); print("parents:", [("%08x" % p, k) for p, k in c.most_common(25)])
