"""python allevents.py : table of all event ids -> vtable/execute/serializer + handler calls (saved to events.tsv)."""
import os
import re, struct, pefile, capstone
pe = pefile.PE(os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "InfiniteCrisis.exe")), fast_load=True)
B = pe.OPTIONAL_HEADER.ImageBase; d = pe.get_memory_mapped_image()
L = open("full.asm").read().split("\n")
pat = re.compile(r"mov dword ptr \[e.. \+ 8\], (0x[0-9a-f]+|\d+)$")
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
seen = {}
for i, l in enumerate(L):
    m = pat.search(l)
    if not m: continue
    if not ("0x300400" in L[i+1] + L[i+2] or "+ 0xc], 0x" in L[i+1]): continue
    eid = int(m.group(1), 0)
    if eid > 0x3000 or eid in seen: continue
    vt = None
    for j in range(i, i + 14):
        mm = re.search(r"mov dword ptr \[e..\], 0x(1[5-7][0-9a-f]{5})$", L[j])
        if mm and int(mm.group(1), 16) - B != 0x11a7da0: vt = int(mm.group(1), 16) - B
    if not vt: continue
    ex, se = [struct.unpack_from("<I", d, vt + o)[0] - B for o in (4, 0x1c)]
    calls = []
    for ins in md.disasm(d[ex:ex + 0x120], B + ex):
        if ins.mnemonic == "call" and ins.op_str.startswith("0x"):
            calls.append(int(ins.op_str, 16) - B)
        if ins.mnemonic == "int3": break
    seen[eid] = (vt, ex, se, calls)
with open("events.tsv", "w") as f:
    for eid in sorted(seen):
        vt, ex, se, calls = seen[eid]
        f.write("%#x\t%x\t%x\t%x\t%s\n" % (eid, vt, ex, se, " ".join("%x" % c for c in calls)))
print(len(seen), "events")
