import struct, pefile
EXE = r"D:\SteamLibrary\steamapps\common\Infinite Crisis Steam\InfiniteCrisis.exe"
pe = pefile.PE(EXE, fast_load=True); BASE = pe.OPTIONAL_HEADER.ImageBase
data = pe.get_memory_mapped_image()
p = struct.pack("<3I", BASE+0x6b4b40, BASE+0x6b4b40, BASE+0x6b4b40)
i = data.find(p)
while i >= 0:
    s = [struct.unpack_from("<I", data, i+4*k)[0]-BASE for k in range(11)]
    if s[9] == 0x6b4d80:
        print("%x: %s" % (i, " ".join("%x" % x for x in s)))
    i = data.find(p, i+4)
