"""navprobe.py <lbx hex> <lby hex> <x> <y> <z> [radius]: ask the live client's
pathfinder (rva 0xfb400) for the nearest navigable point; prints the result."""
import struct, sys, time, os, tracer
pid = tracer.find_pid(tracer.PROCESS_NAME); t = tracer.Tracer(pid); b = t.find_base()
u = lambda a: struct.unpack("<I", t.read(a, 4))[0]
lbx, lby = int(sys.argv[1], 16), int(sys.argv[2], 16)
x, y, z = map(float, sys.argv[3:6]); rad = float(sys.argv[6]) if len(sys.argv) > 6 else 50.0
agent = int(open("logs/agent.txt").read().strip(), 16)
S = b + 0x190e580; O = b + 0x190e5c0
f = lambda v: struct.unpack("<I", struct.pack("<f", v))[0]
vals = [b + 0x11a7de0, 1, lbx | lby << 8, 0, f(x), f(y), f(z), f(1.0), 0, 0, 0]
lines = ["poke32 %x %x" % (S + 4 * i, v) for i, v in enumerate(vals)]
lines += ["poke32 %x %x" % (O + 4 * i, v) for i, v in enumerate([b + 0x11a7de0, 0, 0xffff, 0, 0, 0, 0, f(1.0), 0, 0, 0])]
lines.append("callthis fb400 %x %x %x %x 0 %x" % (u(b + 0x1762e60), agent, S, O, f(rad)))
open("logs/tracer.inject.tmp", "w").write("\n".join(lines) + "\n"); os.replace("logs/tracer.inject.tmp", "logs/tracer.inject")
time.sleep(3.5)
d = t.read(O, 0x2c)
print("in lb %02x %02x (%.1f, %.1f, %.1f) -> out region %d lb %02x %02x origin (%.2f, %.2f, %.2f)" % (lbx, lby, x, y, z, struct.unpack_from("<I", d, 4)[0], d[8], d[9], *struct.unpack_from("<3f", d, 0x10)))
