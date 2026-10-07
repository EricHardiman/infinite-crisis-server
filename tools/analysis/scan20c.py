import re, pefile
EXE = r"D:\SteamLibrary\steamapps\common\Infinite Crisis Steam\InfiniteCrisis.exe"
pe = pefile.PE(EXE, fast_load=True)
data = pe.get_memory_mapped_image()
text = [s for s in pe.sections if s.Name.startswith(b".text")][0]
ts, te = text.VirtualAddress, text.VirtualAddress + text.Misc_VirtualSize
blob = data[ts:te]
out=set()
def chk(p):
    back = blob[p-40:p]
    if re.search(rb"\x8d[\x48-\x4f]\x04|\x83\xc1\x04", back): out.add(ts+p)
for m in re.finditer(rb"\x8b[\x40-\x7f]\x20", blob):
    if re.search(rb"\xff[\xd0-\xd7]", blob[m.end():m.end()+20]): chk(m.start())
for m in re.finditer(rb"\xff[\x50-\x57]\x20", blob): chk(m.start())
print(len(out), " ".join("%x"%x for x in sorted(out)))
