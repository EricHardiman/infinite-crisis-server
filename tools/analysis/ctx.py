"""python ctx.py <rva>... : disassemble from function start to rva+0x30 and show last 22 lines"""
import os
import sys, subprocess, pefile
EXE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "InfiniteCrisis.exe"))
pe = pefile.PE(EXE, fast_load=True); data = pe.get_memory_mapped_image()
import capstone
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
B = pe.OPTIONAL_HEADER.ImageBase
for a in sys.argv[1:]:
    t = int(a,16); p = t
    while not (data[p-1] == 0xCC and data[p] != 0xCC): p -= 1
    lines=[]
    for i in md.disasm(data[p:t+0x18], B+p):
        lines.append("%8x  %-6s %s" % (i.address-B, i.mnemonic, i.op_str))
    print("== %s (func %x)" % (a, p)); print("\n".join(lines[-20:]))
