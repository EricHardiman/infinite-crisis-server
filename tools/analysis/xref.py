"""python xref.py <rva hex>...  -- find E8/E9 callers and absolute pointer refs to each RVA."""
import sys, struct, pefile, re
EXE = r"D:\SteamLibrary\steamapps\common\Infinite Crisis Steam\InfiniteCrisis.exe"
pe = pefile.PE(EXE, fast_load=True)
BASE = pe.OPTIONAL_HEADER.ImageBase
data = pe.get_memory_mapped_image()
text = [s for s in pe.sections if s.Name.startswith(b".text")][0]
ts, te = text.VirtualAddress, text.VirtualAddress + text.Misc_VirtualSize
for a in sys.argv[1:]:
    t = int(a, 16)
    calls = []
    for m in re.finditer(rb"[\xe8\xe9]", data[ts:te]):
        p = ts + m.start()
        rel = struct.unpack_from("<i", data, p + 1)[0]
        if p + 5 + rel == t:
            calls.append("%x%s" % (p, "j" if data[p] == 0xe9 else ""))
    ptrs = []
    pat = struct.pack("<I", BASE + t)
    i = data.find(pat)
    while i >= 0:
        ptrs.append("%x" % i); i = data.find(pat, i + 1)
    print("%x: calls from %s | ptr refs at %s" % (t, " ".join(calls) or "-", " ".join(ptrs) or "-"))
