"""Usage: python dis.py <rva hex> [max_bytes]  -- disassemble function at RVA until int3 padding.
All addresses printed as RVAs (call targets too)."""
import sys, struct, pefile, capstone
EXE = r"D:\SteamLibrary\steamapps\common\Infinite Crisis Steam\InfiniteCrisis.exe"
pe = pefile.PE(EXE, fast_load=True)
BASE = pe.OPTIONAL_HEADER.ImageBase
data = pe.get_memory_mapped_image()
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
md.detail = False
def cstr(rva, n=80):
    if rva < 0 or rva >= len(data): return None
    s = data[rva:rva+n].split(b"\0")[0]
    if len(s) >= 4 and all(32 <= c < 127 for c in s): return s.decode()
    return None
def dis(rva, maxb=0x600):
    end = rva + maxb
    pos = rva
    while pos < end:
        got = False
        for i in md.disasm(data[pos:end], BASE + pos):
            got = True
            r = i.address - BASE
            op = i.op_str
            note = ""
            import re
            for m in re.findall(r"0x[0-9a-f]+", op):
                v = int(m, 16)
                if BASE <= v < BASE + len(data):
                    s = cstr(v - BASE)
                    op = op.replace(m, "rva_%x" % (v - BASE))
                    if s: note += '  ; "%s"' % s
            print("%8x  %-8s %s%s" % (r, i.mnemonic, op, note))
            pos = r + i.size
            if i.mnemonic == "int3":
                return
        if not got:
            print("%8x  (bad)" % pos); pos += 1
if __name__ == "__main__":
    dis(int(sys.argv[1], 16), int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x600)
