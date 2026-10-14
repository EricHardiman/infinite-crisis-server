"""python evid.py <event id hex>... : find ctor, vtable, execute, serializer for event ids."""
import os
import sys, re, struct, pefile
pe = pefile.PE(os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "InfiniteCrisis.exe")), fast_load=True)
B = pe.OPTIONAL_HEADER.ImageBase; d = pe.get_memory_mapped_image()
L = open("full.asm").read().split("\n")
for a in sys.argv[1:]:
    eid = int(a, 16)
    pat = re.compile(r"mov dword ptr \[e.. \+ 8\], (0x%x|%d)$" % (eid, eid))
    for i, l in enumerate(L):
        if pat.search(l) and "0x300400" in L[i+1] + L[i+2] or (pat.search(l) and "+ 0xc], 0x" in L[i+1]):
            vt = None
            for j in range(i, i + 14):
                m = re.search(r"mov dword ptr \[e..\], 0x(1[5-7][0-9a-f]{5})$", L[j])
                if m and int(m.group(1), 16) - B != 0x11a7da0: vt = int(m.group(1), 16) - B
            if vt:
                ex, de, se = [struct.unpack_from("<I", d, vt + o)[0] - B for o in (4, 0x14, 0x1c)]
                print("event %#x: ctor-site %s flags %s vtable %x execute %x serializer %x" % (eid, l.split()[0], L[i+1].split()[-1], vt, ex, se))
