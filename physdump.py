"""Dump a physics object of the running client. Usage: python physdump.py <entity handle hex> [len hex]
Prints u32 + f32 per dword of [handle] (the physics object)."""
import struct, sys
import tracer
pid = tracer.find_pid(tracer.PROCESS_NAME); t = tracer.Tracer(pid); b = t.find_base()
u = lambda a: struct.unpack("<I", t.read(a, 4))[0]
h = int(sys.argv[1], 16)
n = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x120
p = u(h)
print("handle %x phys %x vtable rva %x" % (h, p, u(p) - b))
d = t.read(p, n)
for o in range(0, n, 4):
    v = struct.unpack_from("<I", d, o)[0]; f = struct.unpack_from("<f", d, o)[0]
    fs = "%.4f" % f if 1e-4 < abs(f) < 1e6 else ""
    print("+%03x %08x %s" % (o, v, fs))
