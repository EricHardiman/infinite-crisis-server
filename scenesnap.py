"""Snapshot scene/camera/cinematic state of the running client. Usage: python scenesnap.py <out file>
C = [[0x1773518]+0xdc] scene controller, E = [[C+0x10c]+0x10] environment, M = [[0x1773518]+0xe4]
camera manager, D = [0x176ba00] camera director, G = [0x17766b0] cinematic manager."""
import struct, sys, json, tracer
pid = tracer.find_pid(tracer.PROCESS_NAME); t = tracer.Tracer(pid); b = t.find_base()
u = lambda a: struct.unpack("<I", t.read(a, 4))[0]
sb = u(b + 0x1773518); C = u(sb + 0xdc); M = u(sb + 0xe4); D = u(b + 0x176ba00); G = u(b + 0x17766b0)
E = u(u(C + 0x10c) + 0x10)
out = {}
for name, addr, n in (("C", C, 0x780), ("E", E, 0x100), ("M", M, 0xc0), ("D", D, 0x100), ("G", G, 0x90)):
    try:
        d = t.read(addr, n)
        out[name] = [struct.unpack_from("<I", d, o)[0] for o in range(0, n, 4)]
    except Exception as e:
        out[name] = []
out["glob"] = [u(b + 0x1776950), u(b + 0x1775900)]
json.dump(out, open(sys.argv[1], "w"))
print({k: len(v) for k, v in out.items()})
