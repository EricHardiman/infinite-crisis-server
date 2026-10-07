import re, struct, pefile
EXE = r"D:\SteamLibrary\steamapps\common\Infinite Crisis Steam\InfiniteCrisis.exe"
pe = pefile.PE(EXE, fast_load=True); BASE = pe.OPTIONAL_HEADER.ImageBase
data = pe.get_memory_mapped_image()
text = [s for s in pe.sections if s.Name.startswith(b".text")][0]
ts, te = text.VirtualAddress, text.VirtualAddress + text.Misc_VirtualSize
blob = data[ts:te]
hits = []
# mov r32,[r32+0x20] ... call r32   or call [r32+0x20]
for m in re.finditer(rb"\x8b[\x40-\x47\x48-\x4f\x50-\x57\x58-\x5f\x70-\x77\x78-\x7f]\x20", blob):
    p = m.start()
    win = blob[p+3:p+20]
    if re.search(rb"\xff[\xd0-\xd7]", win):
        back = blob[p-60:p]
        # interface at +4 and field 0xfc load
        if b"\xfc\x00\x00\x00" in back:
            hits.append(ts+p)
for m in re.finditer(rb"\xff[\x50-\x57]\x20", blob):
    p = m.start(); back = blob[p-60:p]
    if b"\xfc\x00\x00\x00" in back: hits.append(ts+p)
print(len(hits)); print(" ".join("%x" % h for h in hits))
