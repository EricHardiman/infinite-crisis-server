"""Dump the notice-subscriber hash map of an entity (read-only).
Usage: python noticemap.py <entity hex> [notice id hex]
Layout (rva 0x820f0): comp = [entity+0x34]; map = [comp+8]; [map]=bucket count
(bit31 = single bucket at map+0xc), [map+4]=count, [map+0xc]=bucket array;
node: [n]=next, [n+4]=key, value at n+8."""
import os
import struct, sys
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))
import tracer
t = tracer.Tracer(tracer.find_pid(tracer.PROCESS_NAME))
u = lambda a: struct.unpack("<I", t.read(a, 4))[0]
ent = int(sys.argv[1], 16)
want = int(sys.argv[2], 16) if len(sys.argv) > 2 else None
comp = u(ent + 0x34)
m = u(comp + 8)
print("comp %#x map %#x" % (comp, m))
if not m:
    sys.exit("no map")
nb, cnt = u(m), u(m + 4)
print("buckets %#x count %d" % (nb, cnt))
if nb & 0x80000000:
    heads = [m + 0xc]
else:
    arr = u(m + 0xc)
    heads = [arr + 4 * i for i in range(nb & 0x7fffffff)]
keys = []
for h in heads:
    n = u(h)
    while n:
        keys.append((u(n + 4), n))
        n = u(n)
for k, n in sorted(keys):
    mark = "  <==" if k == want else ""
    print("  key %#010x node %#x value %#x%s" % (k, n, u(n + 8), mark))
