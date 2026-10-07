"""python memscan.py <hex dword value> : find all locations in the client holding that u32; print surrounding dwords."""
import ctypes, struct, sys
import ctypes.wintypes as wt
import tracer
k32 = tracer.k32
class MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_ulonglong), ("AllocationBase", ctypes.c_ulonglong),
                ("AllocationProtect", wt.DWORD), ("PartitionId", wt.WORD), ("RegionSize", ctypes.c_ulonglong),
                ("State", wt.DWORD), ("Protect", wt.DWORD), ("Type", wt.DWORD)]
k32.VirtualQueryEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.POINTER(MBI), ctypes.c_size_t]
pid = tracer.find_pid(tracer.PROCESS_NAME)
t = tracer.Tracer(pid); t.base = t.find_base()
val = int(sys.argv[1], 16); pat = struct.pack("<I", val)
addr = 0x10000; mbi = MBI()
while addr < 0x7FFF0000 and k32.VirtualQueryEx(t.hproc, addr, ctypes.byref(mbi), ctypes.sizeof(mbi)):
    size = mbi.RegionSize
    if mbi.State == 0x1000 and mbi.Protect in (0x04, 0x02, 0x40, 0x20) and size < 0x8000000:
        try:
            buf = t.read(mbi.BaseAddress, size)
        except OSError:
            buf = b""
        i = buf.find(pat)
        while i >= 0:
            if i % 4 == 0:
                lo = max(0, i - 0x20)
                ctx = struct.unpack_from("<%dI" % ((min(len(buf), i + 0x14) - lo) // 4), buf, lo)
                print("%08x: %s" % (mbi.BaseAddress + i, " ".join(("[%x]" if lo + 4*k == i else "%x") % v for k, v in enumerate(ctx))))
            i = buf.find(pat, i + 1)
    addr = mbi.BaseAddress + size
