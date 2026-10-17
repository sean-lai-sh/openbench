# A/A band + side split. usage: aastats.py <out-dir>   (tokens = boot.tok, bootstrap 10k seed 0, aa-2 vs aa-1, infra/hang excluded from tokens)
import json,glob,sys,collections
sys.path.insert(0,'/workspace/openbench-ab/results/step5-opus-aa-1017'); sys.path.insert(0,'/tmp/ob-step4')
from boot import boot,tok
from thesis.ab.summarize import row_cost, params_strip_status
from math import comb
def fisher(a,na,b,nb):
    r1,c1,n=na,a+b,na+nb; pr=lambda x: comb(c1,x)*comb(n-c1,r1-x)/comb(n,r1); p0=pr(a)
    return min(1.0,sum(pr(x) for x in range(max(0,r1+c1-n),min(r1,c1)+1) if pr(x)<=p0*(1+1e-7)))
EX=("infra","rate_limited","stalled","incompatible","hang")
d=sys.argv[1]
for prd in glob.glob(d+'/*/cells'):
    S={s:[json.load(open(p)) for p in glob.glob(f"{prd}/{s}/*/*.json")] for s in ("aa-1","aa-2")}
    first=collections.Counter(r.get("first_side") for s in S for r in S[s])
    cost=sum(row_cost(r) or 0 for s in S for r in S[s])
    print(f"{prd.split('/')[-2]} first_side={dict(first)} cost=${cost:.2f} strip={params_strip_status(S['aa-1'],S['aa-2'])} upstream={dict(collections.Counter(r.get('upstream_model') for s in S for r in S[s]))}")
    T={}
    for s in S:
        rs=S[s]; cl=collections.Counter(r.get("failure_class") for r in rs); T[s]=[tok(r) for r in rs if r.get("failure_class") not in EX]
        miss=sum(1 for r in rs if not r.get("success")); infra=sum(1 for r in rs if r.get("failure_class") in EX)
        print(f"  {s}: n={len(rs)} solved={sum(1 for r in rs if r.get('success'))} not-solved={miss} infra+hang={infra} classes={dict(cl)} tok mean={sum(T[s])/max(1,len(T[s])):.0f}")
    pt,lo,hi=(100*v for v in boot(T["aa-1"],T["aa-2"]))
    print(f"  A/A band (aa-2 vs aa-1 total tokens, non-infra/hang): {pt:+.1f}% [{lo:+.1f}%, {hi:+.1f}%]")
    for name,f in (("not solved (incl. infra/hang)",lambda r: not r.get("success")),("infra or hang",lambda r: r.get("failure_class") in EX)):
        a=sum(1 for r in S["aa-1"] if f(r)); b=sum(1 for r in S["aa-2"] if f(r))
        print(f"  {name}: aa-1 {a}/{len(S['aa-1'])}, aa-2 {b}/{len(S['aa-2'])}, Fisher two-sided p={fisher(a,len(S['aa-1']),b,len(S['aa-2'])):.2g}")
    # by launch position within each trial (first-launched vs second-launched side)
    fs=next(iter(first))
    if fs:
        sec=[s for s in S if s!=fs][0]
        a=sum(1 for r in S[fs] if not r.get("success")); b=sum(1 for r in S[sec] if not r.get("success"))
        print(f"  by launch order: first-launched {fs} not solved {a}/{len(S[fs])}, second {sec} {b}/{len(S[sec])}, p={fisher(a,len(S[fs]),b,len(S[sec])):.2g}")
