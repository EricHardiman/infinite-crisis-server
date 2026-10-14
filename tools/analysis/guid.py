import os
import sys, struct, pefile
EXE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "InfiniteCrisis.exe"))
pe = pefile.PE(EXE, fast_load=True); BASE = pe.OPTIONAL_HEADER.ImageBase
data = pe.get_memory_mapped_image()
OFF = int(sys.argv[2]) if len(sys.argv)>2 else 0
g = data[int(sys.argv[1],16):int(sys.argv[1],16)+16]
print(g.hex())
i = data.find(g)
while i >= 0:
    refs = []
    pat = struct.pack("<I", BASE + i + OFF); j = data.find(pat)
    while j >= 0:
        refs.append("%x" % j); j = data.find(pat, j+1)
    print("copy at %x refs: %s" % (i, " ".join(refs)))
    i = data.find(g, i+1)
