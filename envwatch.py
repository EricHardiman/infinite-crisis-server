import struct, time, sys, tracer
pid=tracer.find_pid(tracer.PROCESS_NAME); t=tracer.Tracer(pid); b=t.find_base()
u=lambda a: struct.unpack("<I", t.read(a,4))[0]
sb=u(b+0x1773518); C=u(sb+0xdc)
last=None; t0=time.time()
while time.time()-t0 < float(sys.argv[1]):
    env=u(C+0x11c); fog=t.read(C+0x39,1)[0]; amb=struct.unpack("<f",t.read(C+0x2c8,4))[0]
    cur=(env,fog,round(amb,2))
    if cur!=last:
        print("%6.1fs env %x fog %d ambient %.2f"%(time.time()-t0,env,fog,amb)); last=cur
    time.sleep(0.1)
