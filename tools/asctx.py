"""python asctx.py <line> [before] [after]: print classes_all.txt lines around <line>, plus enclosing class/function."""
import re, sys
L = open("gfx/classes_all.txt").read().split("\n")
i = int(sys.argv[1]) - 1; b = int(sys.argv[2]) if len(sys.argv) > 2 else 60; a = int(sys.argv[3]) if len(sys.argv) > 3 else 20
fn = cls = None
for j in range(i, max(0, i - 5000), -1):
    if fn is None:
        m = re.match(r"^[0-9a-f]{4} Push r\d, '([A-Za-z_0-9]+)'$", L[j])
        if m and "function" in L[j + 1]: fn = m.group(1)
    if L[j].startswith("==== tag 59"):
        for k in range(j, j + 120):
            mm = re.match(r"^[0-9a-f]{4} Push '([A-Za-z_0-9]+)'$", L[k])
            if mm and "function2" in L[k + 1]: cls = mm.group(1); break
        break
print("### class %s, function %s" % (cls, fn))
skip = re.compile(r"^\s*[0-9a-f]{4} (GetVariable|GetMember|Pop|Not)\s*$")
for l in L[i - b:i + a]:
    if not skip.match(l): print(l[:150])
