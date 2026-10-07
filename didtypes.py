"""Dump the client's live DID-prefix -> data-type table (rva 0x1768b30)."""
import struct, tracer
pid = tracer.find_pid(tracer.PROCESS_NAME)
t = tracer.Tracer(pid); t.base = t.find_base()
tab = struct.unpack("<256I", t.read(t.base + 0x1768b30, 1024))
inv = {}
for prefix, typ in enumerate(tab):
    if typ: inv.setdefault(typ, []).append(prefix)
for typ in sorted(inv): print("type %#04x <- DID prefixes %s" % (typ, " ".join("%02x" % p for p in inv[typ])))
