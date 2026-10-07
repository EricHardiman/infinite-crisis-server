import re, sys, pefile, capstone
EXE = r"D:\SteamLibrary\steamapps\common\Infinite Crisis Steam\InfiniteCrisis.exe"
pe = pefile.PE(EXE, fast_load=True); BASE = pe.OPTIONAL_HEADER.ImageBase
data = pe.get_memory_mapped_image()
text = [s for s in pe.sections if s.Name.startswith(b".text")][0]
ts, te = text.VirtualAddress, text.VirtualAddress + text.Misc_VirtualSize
blob = data[ts:te]
# pattern: mov r,[r+0x20] ; (<=14 bytes) ; call r   OR call [r+0x20]; require 'ret 0xc'-style callee => 3 pushes; just list all, with region filter
lo, hi = int(sys.argv[1],16), int(sys.argv[2],16)
out=[]
for m in re.finditer(rb"\x8b[\x40-\x7f]\x20", blob):
    p = ts+m.start()
    if lo<=p<hi and re.search(rb"\xff[\xd0-\xd7]", blob[m.start()+3:m.start()+24]): out.append(p)
for m in re.finditer(rb"\xff[\x50-\x57]\x20", blob):
    p = ts+m.start()
    if lo<=p<hi: out.append(p)
print(len(out), " ".join("%x"%x for x in sorted(out)))
