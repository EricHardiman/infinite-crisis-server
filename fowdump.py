"""Dump the fog-of-war component of an entity. Usage: python fowdump.py <entity handle hex>"""
import struct, sys, tracer
pid=tracer.find_pid(tracer.PROCESS_NAME); t=tracer.Tracer(pid); b=t.find_base()
u=lambda a: struct.unpack("<I", t.read(a,4))[0]
h=int(sys.argv[1],16); c=u(h+0x88)
d=t.read(c,0x1c0)
print("handle %x comp %x vt %x owner %x"%(h,c,u(c)-b,u(c+4)))
print("last update:", struct.unpack_from("<d",d,0x168)[0], " now:", struct.unpack("<d",t.read(b+0x1777a90,8))[0])
print(" ".join("%x:%x"%(o,struct.unpack_from("<I",d,o)[0]) for o in range(0x8,0x1c0,4) if struct.unpack_from("<I",d,o)[0]))
