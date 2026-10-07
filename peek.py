"""Read memory of the running client. Usage: python peek.py "<expr>" ...
expr: hex numbers, +, [x] u32 deref, base = image base. e.g. "[[base+17758d4]+64]" """
import ctypes, struct, sys
import tracer
pid = tracer.find_pid(tracer.PROCESS_NAME)
t = tracer.Tracer(pid); t.base = t.find_base()
class C: pass
c = C(); c.Base = t.base
for e in sys.argv[1:]:
    try:
        v = t.ev(e, c); print(f"{e} = {v:#x}  (rva {v - t.base:#x})")
    except Exception as ex:
        print(e, "ERR", ex)
