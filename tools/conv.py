import sys,struct
sys.path.insert(0, r"D:/SteamLibrary/steamapps/common/Infinite Crisis Steam/_server/tools")
import rplib
strs={}
for l in open(r"D:/SteamLibrary/steamapps/common/Infinite Crisis Steam/_server/tools/strings_all.tsv",encoding="utf-8"):
    f=l.rstrip("\n").split("\t")
    if len(f)>=4 and f[0]=="0xa0000256.rp":
        strs.setdefault(int(f[2],16),f[3])
p=[x for x in rplib.packs() if 'a0000256' in x][0]
ids,data=rplib.load_pack(p)
start=int(sys.argv[1],16)
pos=start
n=struct.unpack_from("<I",data,pos)[0]; pos+=4
print("count",n)
def si(pos):
    mode=data[pos]
    if mode==0:
        tok,tbl=struct.unpack_from("<II",data,pos+1)
        assert data[pos+9:pos+11]==b"\0\0",data[pos:pos+16].hex()
        return (tok,tbl),pos+11
    elif mode==1:
        ln=data[pos+1]
        assert ln<0x80
        s=data[pos+2:pos+2+2*ln].decode("utf-16le")
        assert data[pos+2+2*ln:pos+4+2*ln]==b"\0\0",data[pos:pos+16].hex()
        return s,pos+4+2*ln
    raise Exception("mode %d at %x"%(mode,pos))
def show(s):
    if isinstance(s,tuple): return "%08x:%r"%(s[0],strs.get(s[0],"?"))
    return repr(s)
for i in range(n):
    key,npart,nl=struct.unpack_from("<III",data,pos); pos+=12
    print("conv key %#x participants %d lines %d @%x"%(key,npart,nl,pos-12))
    for j in range(nl):
        p0=pos
        spk=struct.unpack_from("<I",data,pos)[0]; pos+=4
        name,pos=si(pos)
        snd=struct.unpack_from("<I",data,pos)[0]; pos+=4
        text,pos=si(pos)
        dur,flags,img=struct.unpack_from("<fII",data,pos); pos+=12
        movie,pos=si(pos)
        rest=data[pos:pos+17]; 
        # unknown tail: try fixed 17
        print("   spk %d name %s snd %08x dur %.2f flags %#x img %08x movie %s tail %s | %s"%(spk,show(name),snd,dur,flags,img,show(movie),rest.hex(),show(text)))
        pos+=17
print("end %x"%pos)
