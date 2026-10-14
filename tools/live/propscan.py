"""Scan the live client's property-definition registry (read-only).
Needs propdef.py to have run once in this game session (it stores the registry
pointer at scratch rva 0x190e480). Registry hash (lookup rva 0xfee60):
[reg+0x20] bucket count (bit31 = single bucket at reg+0x2c), [reg+0x24] count,
[reg+0x2c] bucket array; node: +4 next, +8 property id, +0xc kind,
+0x10 raw (group = byte +0x12), +0x14 flags (0x10000 = listeners notified).
Usage: python tools/live/propscan.py [kind] [group] [flags mask] [lo hex] [hi hex]"""
import struct, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import tracer
t = tracer.Tracer(tracer.find_pid(tracer.PROCESS_NAME))
b = t.find_base()
u = lambda a: struct.unpack("<I", t.read(a, 4))[0]
reg = u(b + 0x190e480)
if not reg:
    sys.exit("registry pointer not set: run propdef.py once first")
kind = int(sys.argv[1]) if len(sys.argv) > 1 else None
group = int(sys.argv[2]) if len(sys.argv) > 2 else None
mask = int(sys.argv[3], 16) if len(sys.argv) > 3 else 0
lo = int(sys.argv[4], 16) if len(sys.argv) > 4 else 0
hi = int(sys.argv[5], 16) if len(sys.argv) > 5 else 0xFFFFFFFF
nb, cnt = u(reg + 0x20), u(reg + 0x24)
heads = [reg + 0x2c] if nb & 0x80000000 else [u(reg + 0x2c) + 4 * i for i in range((nb & 0x7fffffff))]
rows = []
for h in heads:
    n = u(h)
    while n:
        pid, k, raw, fl = u(n + 8), u(n + 0xc), u(n + 0x10), u(n + 0x14)
        g = (raw >> 16) & 0xff
        if (kind is None or k == kind) and (group is None or g == group) and (fl & mask) == mask and lo <= pid <= hi:
            rows.append((pid, k, g, raw, fl))
        n = u(n + 4)
print("registry %#x: %d defs, %d match" % (reg, cnt, len(rows)))
for pid, k, g, raw, fl in sorted(rows):
    print("  %#010x kind %d group %d raw %08x flags %08x" % (pid, k, g, raw, fl))
