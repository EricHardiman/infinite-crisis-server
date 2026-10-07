"""Minimal AS2 (SWF/GFX) action disassembler: python swf_as2.py file.gfx [filter]
Prints DoAction/DoInitAction bytecode with constant-pool strings resolved."""
import struct, sys

OPS = {0x04:"NextFrame",0x06:"Play",0x07:"Stop",0x0A:"Add",0x0B:"Subtract",0x0C:"Multiply",0x0D:"Divide",0x0E:"Equals",0x0F:"Less",
0x10:"And",0x11:"Or",0x12:"Not",0x17:"Pop",0x1C:"GetVariable",0x1D:"SetVariable",0x26:"Trace",0x34:"GetTime",0x3A:"Delete",0x3B:"Delete2",
0x3C:"DefineLocal",0x3D:"CallFunction",0x3E:"Return",0x3F:"Modulo",0x40:"NewObject",0x41:"DefineLocal2",0x42:"InitArray",0x43:"InitObject",
0x44:"TypeOf",0x47:"Add2",0x48:"Less2",0x49:"Equals2",0x4A:"ToNumber",0x4B:"ToString",0x4C:"PushDuplicate",0x4D:"StackSwap",0x4E:"GetMember",
0x4F:"SetMember",0x50:"Increment",0x51:"Decrement",0x52:"CallMethod",0x53:"NewMethod",0x54:"InstanceOf",0x55:"Enumerate2",0x60:"BitAnd",
0x61:"BitOr",0x62:"BitXor",0x63:"BitLShift",0x64:"BitRShift",0x65:"BitURShift",0x66:"StrictEquals",0x67:"Greater",0x68:"StringGreater",
0x69:"Extends",0x2A:"Throw",0x2B:"CastOp",0x2C:"ImplementsOp",0x81:"GotoFrame",0x83:"GetURL",0x87:"StoreRegister",0x88:"ConstantPool",
0x8E:"DefineFunction2",0x96:"Push",0x99:"Jump",0x9B:"DefineFunction",0x9D:"If",0x9E:"Call",0x9F:"GotoFrame2",0x8C:"GoToLabel",0x94:"With",0x8F:"Try"}

def cstr(b, p):
    e = b.index(b"\0", p); return b[p:e].decode("latin1"), e + 1

def dis(code, out, indent=0, pool=None):
    pool = pool or []
    p = 0; pad = "  " * indent
    while p < len(code):
        op = code[p]; start = p; p += 1
        if op == 0: break
        ln = 0
        if op >= 0x80:
            ln = struct.unpack_from("<H", code, p)[0]; p += 2
        body = code[p:p+ln]; p += ln
        name = OPS.get(op, "op%02x" % op); arg = ""
        if op == 0x88:
            n = struct.unpack_from("<H", body, 0)[0]; q = 2; pool = []
            for _ in range(n):
                s, q = cstr(body, q); pool.append(s)
            arg = "(%d strings)" % n
        elif op == 0x96:
            q = 0; vals = []
            while q < len(body):
                t = body[q]; q += 1
                if t == 0: s, q = cstr(body, q); vals.append(repr(s))
                elif t == 1: vals.append(str(struct.unpack_from("<f", body, q)[0])); q += 4
                elif t == 2: vals.append("null")
                elif t == 3: vals.append("undefined")
                elif t == 4: vals.append("r%d" % body[q]); q += 1
                elif t == 5: vals.append("true" if body[q] else "false"); q += 1
                elif t == 6:
                    hi, lo = struct.unpack_from("<II", body, q); vals.append(str(struct.unpack("<d", struct.pack("<II", lo, hi))[0])); q += 8
                elif t == 7: vals.append(str(struct.unpack_from("<i", body, q)[0])); q += 4
                elif t == 8: i = body[q]; q += 1; vals.append(repr(pool[i]) if i < len(pool) else "c%d" % i)
                elif t == 9: i = struct.unpack_from("<H", body, q)[0]; q += 2; vals.append(repr(pool[i]) if i < len(pool) else "c%d" % i)
                else: vals.append("?%d" % t); break
            arg = ", ".join(vals)
        elif op in (0x99, 0x9D):
            arg = "-> %04x" % (p + struct.unpack_from("<h", body, 0)[0])
        elif op == 0x87: arg = "r%d" % body[0]
        elif op == 0x9B:
            fn, q = cstr(body, 0); n = struct.unpack_from("<H", body, q)[0]; q += 2; params = []
            for _ in range(n): s, q = cstr(body, q); params.append(s)
            size = struct.unpack_from("<H", body, q)[0]
            out.append("%s%04x function %s(%s) {" % (pad, start, fn, ", ".join(params)))
            dis(code[p:p+size], out, indent + 1, pool); out.append(pad + "}"); p += size; continue
        elif op == 0x8E:
            fn, q = cstr(body, 0); n, regs, flags = struct.unpack_from("<HBH", body, q); q += 5; params = []
            for _ in range(n):
                r = body[q]; q += 1; s, q = cstr(body, q); params.append("%s:r%d" % (s, r))
            size = struct.unpack_from("<H", body, q)[0]
            out.append("%s%04x function2 %s(%s) flags=%#x {" % (pad, start, fn, ", ".join(params), flags))
            dis(code[p:p+size], out, indent + 1, pool); out.append(pad + "}"); p += size; continue
        out.append("%s%04x %s %s" % (pad, start, name, arg))
    return pool

def tags(data):
    # header: sig(3) ver(1) len(4) RECT fps(2) frames(2)
    nbits = data[8] >> 3; p = 8 + (5 + 4 * nbits + 7) // 8 + 4
    while p < len(data):
        hdr = struct.unpack_from("<H", data, p)[0]; p += 2
        code, ln = hdr >> 6, hdr & 0x3F
        if ln == 0x3F: ln = struct.unpack_from("<I", data, p)[0]; p += 4
        yield code, data[p:p+ln]; p += ln
        if code == 0: break

if __name__ == "__main__":
    data = open(sys.argv[1], "rb").read(); flt = sys.argv[2] if len(sys.argv) > 2 else None
    for code, body in tags(data):
        if code in (12, 59):
            out = []
            try: dis(body[2:] if code == 59 else body, out)
            except Exception as e: out.append("!! disasm error %r" % e)
            text = "\n".join(out)
            if flt is None or flt in text:
                print("==== tag %d (%s) len %d" % (code, "DoInitAction sprite %d" % struct.unpack_from("<H", body)[0] if code == 59 else "DoAction", len(body)))
                print(text)
