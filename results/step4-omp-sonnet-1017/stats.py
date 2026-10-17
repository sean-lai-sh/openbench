# step-4 copy of step3 stats.py: OMP A/A band from step 2 (results/aa-sonnet-1016 omp36-aa: +4.1% [-3.4%, +14.0%]); omp-NN ids sort by number.
import json,glob,sys,os
sys.path.insert(0,'/tmp'); sys.path.insert(0,'/tmp/ob-step4')
from boot import boot, tok
from thesis.ab.summarize import row_cost, params_strip_status
R=sys.argv[1] if len(sys.argv)>1 else os.path.dirname(os.path.abspath(__file__))
EX=("infra","rate_limited","stalled","incompatible")
tot=0.0
print("pr | task | without solved | with solved | infra w/o,w | hang w/o,w | tok w/o | tok w | diff [95% CI] | cost | strip")
for d in sorted(glob.glob(f"{R}/*/cells"), key=lambda p:int(p.split('/')[-2].split('-')[-1])):
    pr=d.split('/')[-2]; S={}; cost=0; task=set()
    for s in ("without","with"):
        rs=[json.load(open(p)) for p in glob.glob(f"{d}/{s}/*/*.json")]; S.setdefault('_rows',{})[s]=rs
        for r in rs: cost+=row_cost(r) or 0; task.add(r.get("task"))
        J=[r for r in rs if r.get("failure_class") not in EX]
        S[s]=dict(n=len(rs),j=len(J),ok=sum(1 for r in J if r.get("success")),inf=sum(1 for r in rs if r.get("failure_class") in EX),hang=sum(1 for r in rs if r.get("failure_class")=="hang"),t=[tok(r) for r in J])
    for s in ("without","with"):
        if os.path.exists(f"{R}/{pr}/{s}.incompatible.json") or os.path.exists(f"{R}/{pr}/{s}.infra.json"): S[s]["side"]="SIDE-FAIL"
    tot+=cost
    a,b=S["without"],S["with"]
    m=lambda x: f"{sum(x)/len(x):.0f}" if x else "-"
    if len(a["t"])>1 and len(b["t"])>1 and (sum(a["t"])==0 or sum(b["t"])==0): ci="not measurable (no metered tokens on a side)"
    elif len(a["t"])>1 and len(b["t"])>1:
        pt,lo,hi=(100*v for v in boot(a["t"],b["t"]))
        if lo<=0<=hi: ci="no effect detected (±%.1f%%) %+.1f%% [%+.1f%%, %+.1f%%]"%(max(abs(lo),abs(hi)),pt,lo,hi)
        elif -3.4<=pt<=14.0: ci="no effect detected (inside OMP A/A band -3.4%%..+14.0%%; CI excludes 0) %+.1f%% [%+.1f%%, %+.1f%%]"%(pt,lo,hi)
        else: ci="effect %+.1f%% [%+.1f%%, %+.1f%%]"%(pt,lo,hi)
    else: ci="not measurable (no judged cells on a side)"
    print(f"{pr} | {','.join(sorted(map(str,task)))} | {a['ok']}/{a['j']} {a.get('side','')} | {b['ok']}/{b['j']} {b.get('side','')} | {a['inf']},{b['inf']} | {a['hang']},{b['hang']} | {m(a['t'])} | {m(b['t'])} | {ci} | ${cost:.2f} | {params_strip_status(S['_rows']['without'],S['_rows']['with'])}{' EARLY-STOP' if os.path.exists(f'{R}/{pr}/early-stop.json') else ''}")
print(f"total ${tot:.2f}")
