import struct,tracer,sys
pid=tracer.find_pid(tracer.PROCESS_NAME); t=tracer.Tracer(pid); b=t.find_base()
u=lambda a:struct.unpack("<I",t.read(a,4))[0]
def pos(a):
    d=t.read(a,0x2c); return "region %d lb %02x %02x cell %04x origin (%.2f, %.2f, %.2f)"%(struct.unpack_from("<I",d,4)[0],d[8],d[9],struct.unpack_from("<H",d,10)[0],*struct.unpack_from("<3f",d,0x10))
sb=u(b+0x1773518); print("viewer",pos(sb+0x50))
for a in sys.argv[1:]:
    p=int(a,16); print("phys",a,pos(p+0x7c),"flags",hex(u(p+0x64)))
