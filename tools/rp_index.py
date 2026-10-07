"""Index every record in rp/*.rp into rp_index.tsv:
  did  pack  offset_in_stream  size  first-64-bytes-hex  strings
"""
import os, re, sys
import rplib

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rp_index.tsv")
STR = re.compile(rb"[A-Za-z_][A-Za-z0-9_ .:/\-]{5,80}")
n = bad = 0
with open(OUT, "w", encoding="utf-8") as out:
    for path in rplib.packs():
        name = os.path.basename(path)
        try:
            ids, data = rplib.load_pack(path)
        except Exception as e:
            print("FAIL", name, e, flush=True); bad += 1
            continue
        got = 0
        for did, off, rec in rplib.split_records(ids, data):
            strings = "|".join(s.decode() for s in STR.findall(rec[:4096])[:6])
            out.write("%08x\t%s\t%d\t%d\t%s\t%s\n" % (did, name, off, len(rec), rec[:64].hex(), strings))
            got += 1
        n += got
        if got != len(ids):
            print("PARTIAL", name, got, len(ids), flush=True)
print("records", n, "failed packs", bad)
