import os
import pefile, capstone, time
EXE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "InfiniteCrisis.exe"))
pe = pefile.PE(EXE, fast_load=True); data = pe.get_memory_mapped_image(); B = pe.OPTIONAL_HEADER.ImageBase
for s in pe.sections: print(s.Name, hex(s.VirtualAddress), hex(s.Misc_VirtualSize), hex(s.Characteristics))
text = [s for s in pe.sections if s.Name.startswith(b".text")][0]
ts, te = text.VirtualAddress, text.VirtualAddress + text.Misc_VirtualSize
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
t0=time.time(); pos = ts; n=0
with open("full.asm","w") as f:
    while pos < te:
        last = pos
        for a, size, mn, ops in md.disasm_lite(data[pos:te], B+pos):
            f.write("%x %s %s\n" % (a-B, mn, ops)); last = a-B+size; n+=1
        pos = last + 1 if last < te else te
print(n, time.time()-t0)
