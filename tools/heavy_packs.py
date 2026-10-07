"""Find each champion variant's HEAVY pack: packs containing a character variant
record (DID prefix 0x40, mirrored 0x49) with name property 0x10000433 and
parent-pack property 0x10000730. Writes heavy_packs.json:
  [{pack, variant (0x40 did), token, parent_pack}]"""
import json, os, re, struct
import rplib
out = []
pat = re.compile(rb"\x33\x04\x00\x10\x33\x04\x00\x10\x00\x00\x00\x00(....)\x05\x00\x00\x2b\x00\x00\x00\x00\x00\x00\x00\x00\x30\x07\x00\x10\x30\x07\x00\x10(....)", re.S)
for path in rplib.packs():
    ids, data = rplib.load_pack(path)
    v = [i for i in ids if i >> 24 == 0x40]
    m = pat.search(data)
    if m and v:
        out.append({"pack": int(os.path.basename(path)[2:10], 16), "variants": v,
                    "token": struct.unpack("<I", m.group(1))[0], "parent_pack": struct.unpack("<I", m.group(2))[0]})
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "heavy_packs.json"), "w"), indent=1)
print(len(out), "heavy packs")
print([(hex(o["pack"]), [hex(x) for x in o["variants"]], hex(o["token"]), hex(o["parent_pack"])) for o in out[:6]])
