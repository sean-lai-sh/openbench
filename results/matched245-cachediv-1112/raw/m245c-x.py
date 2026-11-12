import json,glob,os
B=os.path.expanduser("~/h2/matched245-cachediv-1112")
for cell in sorted(glob.glob(B+"/cells/*")):
    rq=cell+"/pi/requests"; n=len(glob.glob(rq+"/*.client.json")); print("##",os.path.basename(cell))
    for k in (2,3):
        if k>n: break
        a=open(f"{rq}/{k-1:04d}.client.json","rb").read(); b=open(f"{rq}/{k:04d}.client.json","rb").read()
        i=0
        while a[i]==b[i]: i+=1
        print(f" call{k} vs {k-1} @byte {i}: prev={a[i-20:i+70]!r}\n                 cur ={b[i-20:i+70]!r}")
    for k in (1,2):
        c=json.load(open(f"{rq}/{k:04d}.client.json")); f=json.load(open(f"{rq}/{k:04d}.forwarded.json"))
        print(f" call{k} client->forwarded keys differ:", [x for x in set(c)|set(f) if c.get(x)!=f.get(x)], "client thinking", c.get("thinking"), c.get("output_config"), "fwd", f.get("thinking"), f.get("output_config"))
    hs=set()
    for f in glob.glob(cell+"/pi/proxy-ledger/*.cache-miss-headers.jsonl"):
        for l in open(f): r=json.loads(l); hs.add(json.dumps({k:v for k,v in (r.get("upstream_headers") or {}).items() if k!="Authorization"},sort_keys=True))
    print(" distinct upstream header sets on missed calls:", len(hs), list(hs)[:2])
    led=[json.loads(l) for f in glob.glob(cell+"/pi/proxy-ledger/*[0-9a-f].jsonl") for l in open(f)]
    print(" endpoint_location", {r.get("endpoint_location") for r in led}, "beta-stripped", {json.dumps(r.get("cc_identity_stripped")) for r in led})
