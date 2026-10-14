"""python upto.py <func rva>... : walk callers upward (max depth 4) until an event execute (vtable slot +4) is found."""
import os
import sys, struct, re, pefile, subprocess
pe = pefile.PE(os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "InfiniteCrisis.exe")), fast_load=True)
B = pe.OPTIONAL_HEADER.ImageBase; d = pe.get_memory_mapped_image()
text = [s for s in pe.sections if s.Name.startswith(b".text")][0]
ts, te = text.VirtualAddress, text.VirtualAddress + text.Misc_VirtualSize
calls = {}
for m in re.finditer(rb"[\xe8\xe9]", d[ts:te]):
    p = ts + m.start(); t = p + 5 + struct.unpack_from("<i", d, p + 1)[0]
    if ts <= t < te: calls.setdefault(t, []).append(p)
asm = open("full.asm").read()
def fstart(p):
    while not (d[p-1] == 0xCC and d[p] != 0xCC): p -= 1
    return p
def event_of(f):
    pat = struct.pack("<I", B + f); i = d.find(pat, 0x1179000); out = []
    while i >= 0:
        vt = i - 4
        m = re.search(r"\n([0-9a-f]+) mov dword ptr \[e..\], 0x%x\n" % (B + vt), asm)
        if m:
            back = asm[max(0, m.start() - 900):m.start()]
            ids = re.findall(r"mov dword ptr \[e.. \+ 8\], (0x[0-9a-f]+|\d+)\n", back)
            if ids: out.append((ids[-1], "%x" % (struct.unpack_from("<I", d, vt + 0x1c)[0] - B)))
        i = d.find(pat, i + 1)
    return out
def walk(f, depth, path):
    ev = event_of(f)
    if ev:
        print("  " * depth + "%x  <== EVENT %s serializer %s   path: %s" % (f, ev[0][0], ev[0][1], " <- ".join("%x" % x for x in path)))
        return
    if depth >= 4: return
    for c in calls.get(f, []):
        walk(fstart(c), depth + 1, path + [fstart(c)])
for a in sys.argv[1:]:
    f = int(a, 16); print("%x:" % f); walk(f, 0, [f])
