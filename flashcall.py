"""Call a function inside the HUD's Flash (Scaleform) movie of the running client.

Usage: python flashcall.py <movie ptr hex> <path> [bool|num arg]
  path e.g. _global.gameplay.mainhud.MainHUD.s_instance.m_ouObjectiveUpdates2.GetEnabledForHudVisibility

Needs the tracer attached (uses logs/tracer.inject). The movie pointer is logged
by the tracer breakpoint at rva 0x49994a ("tracker-enable glue: movie Invoke
call movie=...") whenever the server sends 0x2075.

Movie::Invoke (rva 0xde7ee0, thiscall): (const char* path, GFx::Value* result,
const GFx::Value* args, unsigned nargs). GFx::Value here is 16 bytes:
u32 object interface | u32 type (0 undefined, 1 null, 2 bool, 3 number, 4 string)
| 8-byte value. The result Value is printed after the call.
"""
import os, struct, sys, time
import tracer

INVOKE_RVA = 0xde7ee0
SCRATCH = 0x190e800          # path string; result at -0x20, one argument at -0x40

pid = tracer.find_pid(tracer.PROCESS_NAME); t = tracer.Tracer(pid); base = t.find_base()
movie = int(sys.argv[1], 16); path = sys.argv[2].encode() + bytes(1)
path += bytes(-len(path) % 4)
str_va, res_va, arg_va = base + SCRATCH, base + SCRATCH - 0x20, base + SCRATCH - 0x40
lines = []
for i in range(0, len(path), 4):
    lines.append("poke32 %x %x" % (str_va + i, struct.unpack_from("<I", path, i)[0]))
for i in range(0, 16, 4):
    lines.append("poke32 %x %x" % (res_va + i, 0))
nargs = 0
if len(sys.argv) > 3:
    a = sys.argv[3]
    if a in ("true", "false"):
        val = struct.pack("<IIQ", 0, 2, 1 if a == "true" else 0)
    else:
        val = struct.pack("<IId", 0, 3, float(a))
    for i in range(0, 16, 4):
        lines.append("poke32 %x %x" % (arg_va + i, struct.unpack_from("<I", val, i)[0]))
    nargs = 1
lines.append("callthis %x %x %x %x %x %x" % (INVOKE_RVA, movie, str_va, res_va, arg_va if nargs else 0, nargs))
inj = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "tracer.inject")
open(inj, "w").write("\n".join(lines) + "\n")
time.sleep(3.0)
r = t.read(res_va, 16)
iface, typ = struct.unpack_from("<II", r, 0)
print("result type %d  u64 %#x  f64 %r  (iface %#x)" % (typ, struct.unpack_from("<Q", r, 8)[0],
                                                        struct.unpack_from("<d", r, 8)[0], iface))
log = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "trace.log")
tail = open(log, "rb").read()[-3000:].decode("latin1").splitlines()
print("\n".join(l for l in tail if "INJECT call returned" in l or "INJECT failed" in l or "exception" in l.lower())[-400:])
