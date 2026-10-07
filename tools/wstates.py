"""Extract every world-state (.wc, DID prefix 0x2e) record header from the packs.
Record: u32 did | u32 7 | u32 parent entity DID (prefix 0x2d) | u32 0 | u32 nprops | props...
Each prop starts: u32 id | u32 id(|flags) | u32 type | value (type-dependent).
Writes wstates.tsv: did, pack, parent, nprops, first 40 dwords hex."""
import os, struct, collections
import rplib
out = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "wstates.tsv"), "w")
seen = {}
for path in rplib.packs():
    ids, data = rplib.load_pack(path)
    for did in ids:
        if did >> 24 != 0x2e: continue
        pat = struct.pack("<II", did, 7); k = data.find(pat)
        while k >= 0:
            parent, zero, n = struct.unpack_from("<III", data, k + 8)
            if parent >> 24 == 0x2d and zero == 0 and n < 200:
                words = struct.unpack_from("<40I", data + bytes(160), k + 20)
                if did not in seen:
                    seen[did] = (parent, n)
                    out.write("%08x\t%s\t%08x\t%d\t%s\n" % (did, os.path.basename(path), parent, n, " ".join("%x" % w for w in words)))
                break
            k = data.find(pat, k + 1)
out.close()
par = collections.Counter(p for p, n in seen.values())
print("wstates", len(seen), "distinct parents", len(par))
print("most common parents:", [("%08x" % p, c) for p, c in par.most_common(15)])
print("nprops histogram:", sorted(collections.Counter(n for p, n in seen.values()).items()))
