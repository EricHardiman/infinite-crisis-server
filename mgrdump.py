import struct, sys, tracer
pid = tracer.find_pid(tracer.PROCESS_NAME); t = tracer.Tracer(pid); b = t.find_base()
u = lambda a: struct.unpack("<I", t.read(a, 4))[0]
m = u(u(b + 0x17758d4) + 0x1c)
d = t.read(m, 0x160)
print(" ".join("%x:%x" % (o, struct.unpack_from("<I", d, o)[0]) for o in range(0x60, 0x160, 4)))
