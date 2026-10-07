"""python rp_get.py <did hex> [outfile] : dump one record (hexdump, or write to outfile)."""
import os, sys
import rplib
HERE = os.path.dirname(os.path.abspath(__file__))
did = "%08x" % int(sys.argv[1], 16)
for line in open(os.path.join(HERE, "rp_index.tsv"), encoding="utf-8"):
    f = line.rstrip("\n").split("\t")
    if f[0] == did:
        ids, data = rplib.load_pack(os.path.join(rplib.RP_DIR, f[1]))
        rec = data[int(f[2]):int(f[2]) + int(f[3])]
        if len(sys.argv) > 2:
            open(sys.argv[2], "wb").write(rec); print("wrote", len(rec))
        else:
            for i in range(0, min(len(rec), 0x800), 16):
                c = rec[i:i+16]
                print("%06x  %-48s %s" % (i, c.hex(" "), "".join(chr(b) if 32 <= b < 127 else "." for b in c)))
            print("total", len(rec), "pack", f[1])
        break
else:
    print("not found")
