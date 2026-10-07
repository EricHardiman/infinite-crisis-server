"""python ctx2.py <rva> [after_bytes] : linear disasm from func start; print lines from rva-? to rva+after"""
import sys, pefile, capstone
EXE = r"D:\SteamLibrary\steamapps\common\Infinite Crisis Steam\InfiniteCrisis.exe"
pe = pefile.PE(EXE, fast_load=True); data = pe.get_memory_mapped_image()
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32); B = pe.OPTIONAL_HEADER.ImageBase
t = int(sys.argv[1],16); after = int(sys.argv[2],16) if len(sys.argv)>2 else 0x40
p = t
while not (data[p-1] == 0xCC and data[p] != 0xCC): p -= 1
lines=[(i.address-B, "%8x  %-6s %s" % (i.address-B, i.mnemonic, i.op_str)) for i in md.disasm(data[p:t+after], B+p)]
idx = max(0, next((k for k,(a,_) in enumerate(lines) if a>=t), len(lines))-8)
print("== %x (func %x)" % (t,p)); print("\n".join(l for _,l in lines[idx:]))
