"""python evinfo.py <execute-func rva>... : event id, serializer, name for an event class given its execute function."""
import sys, struct, re, pefile, subprocess
EXE = r"D:\SteamLibrary\steamapps\common\Infinite Crisis Steam\InfiniteCrisis.exe"
pe = pefile.PE(EXE, fast_load=True); B = pe.OPTIONAL_HEADER.ImageBase
d = pe.get_memory_mapped_image()
asm = open("full.asm").read()
for a in sys.argv[1:]:
    f = int(a, 16)
    pat = struct.pack("<I", B + f); i = d.find(pat, 0x1179000)
    while i >= 0:
        vt = i - 4
        ser = struct.unpack_from("<I", d, vt + 0x1c)[0] - B
        m = re.search(r"\n([0-9a-f]+) mov dword ptr \[e..\], 0x%x\n" % (B + vt), asm)
        eid = None
        if m:
            pos = m.start()
            back = asm[max(0, pos - 900):pos]
            ids = re.findall(r"mov dword ptr \[e.. \+ 8\], (0x[0-9a-f]+|\d+)\n", back)
            eid = ids[-1] if ids else None
        print("exec %x: vtable %x, ctor-site %s, event id %s, serializer %x" % (f, vt, m.group(1) if m else None, eid, ser))
        i = d.find(pat, i + 1)
