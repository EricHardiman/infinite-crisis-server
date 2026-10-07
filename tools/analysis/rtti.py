"""python rtti.py <vtable rva>... -- print RTTI class name + base classes for MSVC vtables."""
import sys, struct, pefile
EXE = r"D:\SteamLibrary\steamapps\common\Infinite Crisis Steam\InfiniteCrisis.exe"
pe = pefile.PE(EXE, fast_load=True); BASE = pe.OPTIONAL_HEADER.ImageBase
data = pe.get_memory_mapped_image()
u = lambda a: struct.unpack_from("<I", data, a)[0]
def name(td): return data[td+8:td+200].split(b"\0")[0].decode(errors="replace")
for a in sys.argv[1:]:
    vt = int(a, 16)
    try:
        col = u(vt - 4) - BASE
        sig, off, cd, td, chd = struct.unpack_from("<5I", data, col)
        td -= BASE; chd -= BASE
        nb = u(chd + 8); arr = u(chd + 12) - BASE
        bases = []
        for i in range(nb):
            bcd = u(arr + 4*i) - BASE
            bases.append("%s@%d" % (name(u(bcd) - BASE), struct.unpack_from("<i", data, bcd + 8)[0]))
        print("%x: off=%d %s  bases: %s" % (vt, off, name(td), ", ".join(bases)))
    except Exception as e:
        print("%x: no rtti (%s)" % (vt, e))
