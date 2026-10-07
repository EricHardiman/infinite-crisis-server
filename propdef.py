"""propdef.py <prop id hex>...: look up property definitions in the live client
(registry rva 0x1058d0 -> 0xfee60). Prints kind (+0xc) and storage group (+0x12)."""
import struct, sys, time, os, tracer
pid = tracer.find_pid(tracer.PROCESS_NAME); t = tracer.Tracer(pid); b = t.find_base()
u = lambda a: struct.unpack("<I", t.read(a, 4))[0]
def inject(line):
    open("logs/tracer.inject.tmp", "w").write(line + "\n"); os.replace("logs/tracer.inject.tmp", "logs/tracer.inject")
    time.sleep(2.5)
    for l in reversed(open("logs/trace.log", errors="replace").read()[-4000:].splitlines()):
        if "INJECT call returned" in l:
            return int(l.split("eax=")[1], 16)
S = b + 0x190e480
inject("callthis 1058d0 %x" % S)
reg = u(S)
for a in sys.argv[1:]:
    d = inject("callthis fee60 %x %s" % (reg, a))
    if not d:
        print(a, "NOT REGISTERED"); continue
    print("%s kind %d group %d  raw %08x %08x" % (a, u(d + 0xc), t.read(d + 0x12, 1)[0], u(d + 0x10), u(d + 0x14)))
