# Step-6 remainder stats: Opus OC A/A band labels + Fisher on solved. usage: stats2.py <out-dir>
import json,glob,sys,os
H=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,H); sys.path.insert(0,'/tmp/ob-s6run')
from boot import boot, tok
from math import comb
def fisher_exact(t):
    (a,b),(c,d)=t; r1,c1,n=a+b,a+c,a+b+c+d
    pr=lambda x: comb(c1,x)*comb(n-c1,r1-x)/comb(n,r1)
    p0=pr(a); return None,min(1.0,sum(pr(x) for x in range(max(0,r1+c1-n),min(r1,c1)+1) if pr(x)<=p0*(1+1e-7)))
from thesis.ab.summarize import row_cost, params_strip_status
R=sys.argv[1]; EX=("infra","rate_limited","stalled","incompatible"); LO,HI=-10.4,4.4
tot=0.0
print("pr | task | without solved | with solved | infra w/o,w | hang w/o,w | tok w/o | tok w | tokens diff [95% CI] -> label | solved Fisher p -> label | cost | strip | upstream_model per side (None = infra cell, excluded)")
for d in sorted(glob.glob(f"{R}/*/cells"), key=lambda p:int(p.split('/')[-2])):
    pr=d.split('/')[-2]; S={}; cost=0; task=set(); um={'without':set(),'with':set()}; RW={}
    for s in ("without","with"):
        rs=[json.load(open(p)) for p in glob.glob(f"{d}/{s}/*/*.json")]; RW[s]=rs
        for r in rs: cost+=row_cost(r) or 0; task.add(r.get("task")); um[s].add(r.get("upstream_model"))
        J=[r for r in rs if r.get("failure_class") not in EX]
        S[s]=dict(j=len(J),ok=sum(1 for r in J if r.get("success")),inf=len(rs)-len(J),hang=sum(1 for r in rs if r.get("failure_class")=="hang"),t=[tok(r) for r in J])
    tot+=cost; a,b=S["without"],S["with"]
    m=lambda x: f"{sum(x)/len(x):.0f}" if x else "-"
    if len(a["t"])>1 and len(b["t"])>1 and (sum(a["t"])==0 or sum(b["t"])==0): ci="not measurable (no metered tokens on a side)"
    elif len(a["t"])>1 and len(b["t"])>1:
        pt,lo,hi=(100*v for v in boot(a["t"],b["t"])); c="%+.1f%% [%+.1f%%, %+.1f%%]"%(pt,lo,hi)
        if lo<=0<=hi: ci=f"{c} -> no effect detected (±{max(abs(lo),abs(hi)):.1f}%)"
        elif LO<=pt<=HI: ci=f"{c} -> no effect detected (inside Opus OC A/A band -10.4%..+4.4%)"
        else: ci=f"{c} -> effect"
    else: ci="not measurable (no judged cells on a side)"
    if a["j"] and b["j"]:
        p=fisher_exact([[a["ok"],a["j"]-a["ok"]],[b["ok"],b["j"]-b["ok"]]])[1]; g="gain" if b["ok"]/b["j"]>a["ok"]/a["j"] else "loss"
        fl=f"p={p:.2g} -> "+("pass-rate effect (%s)"%g if p<0.01 else "borderline (%s)"%g if p<0.05 else "no pass-rate effect")
    else: fl="n/a"
    es=' EARLY-STOP' if os.path.exists(f'{R}/{pr}/early-stop.json') else ''
    print(f"{pr} | {','.join(sorted(map(str,task)))} | {a['ok']}/{a['j']} | {b['ok']}/{b['j']} | {a['inf']},{b['inf']} | {a['hang']},{b['hang']} | {m(a['t'])} | {m(b['t'])} | {ci} | {fl} | ${cost:.2f} | {params_strip_status(RW['without'],RW['with'])}{es} | w/o:{','.join(sorted(map(str,um['without'])))} w:{','.join(sorted(map(str,um['with'])))}")
print(f"total ${tot:.2f}")
