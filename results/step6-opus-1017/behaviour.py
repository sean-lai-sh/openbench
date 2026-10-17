# Fisher exact (two-sided) on per-cell behaviour fields, all non-infra cells. usage: behaviour.py <out-dir> <pr>
import json,glob,sys
from math import comb
def fisher_exact(t):
    (a,b),(c,d)=t; r1,c1,n=a+b,a+c,a+b+c+d
    pr=lambda x: comb(c1,x)*comb(n-c1,r1-x)/comb(n,r1)
    p0=pr(a); return None,min(1.0,sum(pr(x) for x in range(max(0,r1+c1-n),min(r1,c1)+1) if pr(x)<=p0*(1+1e-7)))
d,pr=sys.argv[1],sys.argv[2]; EX=("infra","rate_limited","stalled","incompatible")
S={s:[json.load(open(p)) for p in glob.glob(f"{d}/{pr}/cells/{s}/*/*.json")] for s in ("without","with")}
S={s:[r for r in v if r.get("failure_class") not in EX] for s,v in S.items()}
M={"24974":[("global rule followed first (rule_order=global_first)",lambda r:r.get("rule_order")=="global_first")],
   "25226":[("tmpdir folders leaked into workspace (tmpdir_leaked_dirs>0) [headline]",lambda r:(r.get("tmpdir_leaked_dirs") or 0)>0),
            ("permission rejections >0",lambda r:(r.get("permission_rejections") or 0)>0),
            ("solved",lambda r:bool(r.get("success")))]}
for name,f in M.get(pr,[]):
    a=sum(1 for r in S["without"] if f(r)); b=sum(1 for r in S["with"] if f(r)); na,nb=len(S["without"]),len(S["with"])
    p=fisher_exact([[a,na-a],[b,nb-b]])[1]
    print(f"{pr} {name}: without {a}/{na}, with {b}/{nb}, Fisher two-sided p={p:.2g}")
