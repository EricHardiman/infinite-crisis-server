"""recdump.py <pack hex> <offset hex> <len hex> [strings] : dump bytes from a pack's payload."""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rplib

pack = sys.argv[1]
off = int(sys.argv[2], 16)
ln = int(sys.argv[3], 16)
ids, data = rplib.load_pack(os.path.join(rplib.RP_DIR, "0x%s.rp" % pack))
rec = data[off:off + ln]
if len(sys.argv) > 4 and sys.argv[4] == "strings":
    for m in re.finditer(rb"[ -~]{4,}", rec):
        print("%06x %s" % (m.start(), m.group().decode()))
    for m in re.finditer(rb"(?:[ -~]\x00){4,}", rec):
        print("%06x U %s" % (m.start(), m.group().decode("utf-16le")))
else:
    for i in range(0, len(rec), 16):
        c = rec[i:i + 16]
        print("%06x  %-48s %s" % (off + i, c.hex(" "), "".join(chr(b) if 32 <= b < 127 else "." for b in c)))
