"""Dump an inner subscriber hash map (same layout as noticemap.py) and each
subscriber's vtable rva + its slot +4 target. Usage: python subs.py <map hex>"""
import os
import struct, sys
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))
import tracer
t = tracer.Tracer(tracer.find_pid(tracer.PROCESS_NAME))
base = t.find_base()
u = lambda a: struct.unpack("<I", t.read(a, 4))[0]
m = int(sys.argv[1], 16)
nb, cnt = u(m), u(m + 4)
print("buckets %#x count %d" % (nb, cnt))
heads = [m + 0xc] if nb & 0x80000000 else [u(m + 0xc) + 4 * i for i in range(nb & 0x7fffffff)]
for h in heads:
    n = u(h)
    while n:
        key, val = u(n + 4), u(n + 8)
        try:
            vt = u(val)
            slot4 = u(vt + 4) - base
            print("  key %#x obj %#x vtable rva %#x slot+4 rva %#x" % (key, val, vt - base, slot4))
        except OSError:
            print("  key %#x obj %#x (unreadable)" % (key, val))
        n = u(n)
