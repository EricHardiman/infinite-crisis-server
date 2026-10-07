"""Build a crude call graph from full.asm (function = run of code after int3 padding).
Saves callgraph.json: {func_rva_hex: [callee_rva_hex,...]}"""
import re, json
L=open('full.asm').read().split('\n')
g={}; cur=None; prev_int3=True
for l in L:
    p=l.split(' ',1)
    if len(p)<2 or len(p[0])<5: continue
    a=p[0]; ins=p[1]
    if ins.startswith('int3'):
        prev_int3=True; continue
    if prev_int3:
        cur=a; g.setdefault(cur,set()); prev_int3=False
    m=re.match(r'(?:call|jmp) 0x([0-9a-f]+)$',ins)
    if m and cur:
        t=int(m.group(1),16)-0x400000
        if 0<t<0x1100000: g[cur].add('%x'%t)
json.dump({k:sorted(v) for k,v in g.items()},open('callgraph.json','w'))
print(len(g))
