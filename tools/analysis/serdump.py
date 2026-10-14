"""python serdump.py <rva>... : list the read sequence of a serializer (sizes via 0x6fae80, sub-reader calls)."""
import os
import sys, pefile, capstone
pe = pefile.PE(os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "InfiniteCrisis.exe")), fast_load=True)
B = pe.OPTIONAL_HEADER.ImageBase; d = pe.get_memory_mapped_image()
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
NAMES = {0x6fae80: "bytes", 0x21430: "compact", 0x1a9580: "StringInfo", 0x1a7710: "StringInfo-prep",
         0xe4530: "u32 n + u32[] (read)", 0xe4460: "u32 n + u32[] (write)", 0x2b01a0: "{u32,u32}",
         0x70d380: "u8 base", 0x6f8710: "error"}
for a in sys.argv[1:]:
    f = int(a, 16); print("==", hex(f))
    last_push = None
    for ins in md.disasm(d[f:f + 0x400], B + f):
        if ins.mnemonic == "int3": break
        if ins.mnemonic == "push" and ins.op_str.startswith(("1", "2", "4", "8", "0x")) and len(ins.op_str) < 6:
            last_push = ins.op_str
        if ins.mnemonic == "call" and ins.op_str.startswith("0x"):
            t = int(ins.op_str, 16) - B
            n = NAMES.get(t, "sub %x" % t)
            print("   %x %s%s" % (ins.address - B, n, (" " + str(last_push)) if t == 0x6fae80 else ""))
        if ins.mnemonic == "ret": print("   ret")
