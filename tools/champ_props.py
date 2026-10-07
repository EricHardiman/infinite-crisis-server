"""Add texture property DIDs to champions.json: for each champion/costume record
(prefix 0x48) read properties 0x10000384 and 0x10000799 (texture DIDs, prefix 0x13)."""
import json, os, re, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rplib
HERE = os.path.dirname(os.path.abspath(__file__))
roster = json.load(open(os.path.join(HERE, "..", "champions.json")))
want = {c["id"] for c in roster} | {m for c in roster for m in c["costumes"]}
props = {}
pat = re.compile(rb"(...\x48)\x00\x00\x00\x00(.)\x00\x00\x00\x8b\x04\x00\x10\x8b\x04\x00\x10", re.S)
for path in rplib.packs():
    ids, data = rplib.load_pack(path)
    for m in pat.finditer(data):
        did = struct.unpack("<I", m.group(1))[0]
        if did not in want or did in props: continue
        seg = data[m.start():m.start() + 600]
        d = {}
        for pid in (0x10000384, 0x10000799):
            k = seg.find(struct.pack("<II", pid, pid))
            if k >= 0: d["%x" % pid] = struct.unpack_from("<I", seg, k + 8)[0]
        props[did] = d
for c in roster:
    c["tex384"] = props.get(c["id"], {}).get("10000384", 0)
    c["tex799"] = props.get(c["id"], {}).get("10000799", 0)
json.dump(roster, open(os.path.join(HERE, "..", "champions.json"), "w"), indent=1)
print(sum(1 for c in roster if c["tex384"]), "of", len(roster), "have 384;", sum(1 for c in roster if c["tex799"]), "have 799")
print([(c["name"], hex(c["tex384"]), hex(c["tex799"])) for c in roster[:4]])
