import os
import sys, struct, pefile
EXE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "InfiniteCrisis.exe"))
pe = pefile.PE(EXE, fast_load=True); BASE = pe.OPTIONAL_HEADER.ImageBase
data = pe.get_memory_mapped_image()
a = int(sys.argv[1], 16); n = int(sys.argv[2]) if len(sys.argv) > 2 else 16
for i in range(n):
    v = struct.unpack_from("<I", data, a + 4*i)[0]
    print("%x  +%02x  %x" % (a + 4*i, 4*i, v - BASE if v >= BASE else v))
