"""python fstart.py <rva>... -- guess function start (scan back to int3 padding) for an address."""
import os
import sys, pefile
EXE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "InfiniteCrisis.exe"))
pe = pefile.PE(EXE, fast_load=True)
data = pe.get_memory_mapped_image()
for a in sys.argv[1:]:
    p = int(a, 16)
    while not (data[p-1] == 0xCC and data[p] != 0xCC) and not (data[p-1] == 0xC3 and data[p] in (0x55, 0x56, 0x53, 0x83, 0x8b, 0x6a, 0x51)):
        p -= 1
    print("%s -> %x" % (a, p))
