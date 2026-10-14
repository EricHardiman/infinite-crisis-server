import os
import re, pefile
EXE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "InfiniteCrisis.exe"))
pe = pefile.PE(EXE, fast_load=True)
data = pe.get_memory_mapped_image()
text = [s for s in pe.sections if s.Name.startswith(b".text")][0]
ts, te = text.VirtualAddress, text.VirtualAddress + text.Misc_VirtualSize
blob = data[ts:te]
# any load of [reg+0xfc] followed within 40 bytes by a +0x20 vtable call
for m in re.finditer(rb"\x8b[\x80-\xbf]\xfc\x00\x00\x00", blob):
    w = blob[m.end():m.end()+48]
    if re.search(rb"\x8b[\x40-\x7f]\x20", w) or re.search(rb"\xff[\x50-\x57]\x20", w):
        print("%x" % (ts+m.start()))
