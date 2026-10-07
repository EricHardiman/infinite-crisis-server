"""python fs2.py <rva>... : function start from the linear listing (first 'push ebp' after an int3/ret run)."""
import sys, bisect
L = open("full.asm").read().split("\n")
addrs = [int(l.split(" ", 1)[0], 16) if l else 0 for l in L]
for a in sys.argv[1:]:
    i = bisect.bisect_right(addrs, int(a, 16)) - 1
    while i > 0:
        if L[i].endswith("push ebp") and L[i+1].endswith("mov ebp, esp") and (L[i-1].endswith("int3 ") or " ret" in L[i-1] or L[i-1].endswith("int3")):
            break
        i -= 1
    print(a, "->", L[i].split()[0])
