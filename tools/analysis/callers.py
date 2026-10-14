"""python callers.py <func rva> [depth] : print the caller tree (function starts) up to depth."""
import os
import sys, struct, re, bisect, pefile
pe = pefile.PE(os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "InfiniteCrisis.exe")), fast_load=True)
B = pe.OPTIONAL_HEADER.ImageBase; d = pe.get_memory_mapped_image()
text = [s for s in pe.sections if s.Name.startswith(b".text")][0]
ts, te = text.VirtualAddress, text.VirtualAddress + text.Misc_VirtualSize
calls = {}
for m in re.finditer(rb"[\xe8\xe9]", d[ts:te]):
    p = ts + m.start(); t = p + 5 + struct.unpack_from("<i", d, p + 1)[0]
    if ts <= t < te: calls.setdefault(t, []).append(p)
L = open("full.asm").read().split("\n"); addrs = [int(l.split(" ", 1)[0], 16) if l else 0 for l in L]
def fstart(a):
    i = bisect.bisect_right(addrs, a) - 1
    while i > 0:
        if L[i].endswith("push ebp") and L[i+1].endswith("mov ebp, esp") and ("int3" in L[i-1] or " ret" in L[i-1]): break
        i -= 1
    return addrs[i]
def strs(f):
    out = []
    i = bisect.bisect_left(addrs, f)
    for l in L[i:i+400]:
        if "int3" in l: break
        m = re.search(r"push 0x(1[5-8][0-9a-f]{5})$", l)
        if m:
            a = int(m.group(1), 16) - B; s = d[a:a+70].split(b"\0")[0]
            if len(s) > 8 and all(32 <= c < 127 for c in s): out.append(s.decode())
    return out[:2]
def ptrrefs(f):
    pat = struct.pack("<I", B + f); i = d.find(pat, 0x1179000); r = []
    while i >= 0: r.append(i); i = d.find(pat, i + 1)
    return r
seen = set()
def walk(f, depth, maxd):
    tag = "%x %s" % (f, strs(f))
    pr = ptrrefs(f)
    print("  " * depth + tag + (" vtable@" + ",".join("%x" % x for x in pr[:3]) if pr else ""))
    if depth >= maxd or f in seen: return
    seen.add(f)
    for c in sorted(set(fstart(x) for x in calls.get(f, []))):
        walk(c, depth + 1, maxd)
walk(int(sys.argv[1], 16), 0, int(sys.argv[2]) if len(sys.argv) > 2 else 3)
