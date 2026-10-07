import re
L = [l.rstrip("\n").split(" ",2) for l in open("full.asm")]
out=[]
for i,l in enumerate(L):
    hit = False
    if l[1]=="call" and re.fullmatch(r"dword ptr \[e.. \+ 0x20\]", l[2]): hit=True; ci=i
    elif l[1]=="mov" and re.fullmatch(r"(e..), dword ptr \[e.. \+ 0x20\]", l[2]):
        r = l[2][:3]
        for j in range(i+1, min(i+8,len(L))):
            if L[j][1]=="call" and L[j][2]==r: hit=True; ci=j; break
            if L[j][1] in ("call","ret","jmp"): break
    if not hit: continue
    # window: 14 instrs before call; count pushes since last call/ret
    pushes=0; ok=True
    for j in range(ci-1, max(ci-16,0), -1):
        if L[j][1] in ("call","ret","jmp") : break
        if L[j][1]=="push": pushes+=1
    if pushes==3: out.append((l[0], ci))
print(len(out))
for a,ci in out:
    print("== "+a); print("\n".join(" ".join(x) for x in L[ci-9:ci+1]))
