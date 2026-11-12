import json,sys,glob,os
def bps(d):
    raw=json.dumps(d); out=[]
    def walk(o,path):
        if isinstance(o,dict):
            if "cache_control" in o: out.append((path,o["cache_control"]))
            for k,v in o.items(): walk(v,path+[k])
        elif isinstance(o,list):
            for i,v in enumerate(o): walk(v,path+[i])
    for sec in ("tools","system","messages"):
        walk(d.get(sec),[sec])
    res=[]
    for p,cc in out:
        # byte offset of the end of the block carrying the breakpoint, in json.dumps(body)
        sub=d
        for k in p: sub=sub[k]
        frag=json.dumps(sub); off=raw.find(frag)
        res.append({"path":"/".join(map(str,p)),"cache_control":cc,"byte_offset_start":off,"byte_offset_end":off+len(frag) if off>=0 else None})
    return res
for f in sys.argv[1:]:
    d=json.load(open(f)); print(f.split("cells/")[1]); print(" sizes", {k:len(json.dumps(d.get(k))) for k in ("tools","system","messages")}, "n_messages",len(d["messages"]), "n_tools", len(d.get("tools") or []))
    for b in bps(d): print("  ",b)
