import json,glob,sys,os
sys.path.insert(0,'/tmp'); sys.path.insert(0,'/workspace/openbench-ab')
from boot import boot, tok
from thesis.ab.summarize import row_cost
R=sys.argv[1] if len(sys.argv)>1 else os.path.dirname(os.path.abspath(__file__))
EX=("infra","rate_limited","stalled","incompatible")
tot=0.0
print("pr | task | without solved | with solved | infra w/o,w | hang w/o,w | tok w/o | tok w | diff [95% CI] | cost")
for d in sorted(glob.glob(f"{R}/*/cells"), key=lambda p:int(p.split('/')[-2])):
    pr=d.split('/')[-2]; S={}; cost=0; task=set()
    for s in ("without","with"):
        rs=[json.load(open(p)) for p in glob.glob(f"{d}/{s}/*/*.json")]
        for r in rs: cost+=row_cost(r) or 0; task.add(r.get("task"))
        J=[r for r in rs if r.get("failure_class") not in EX]
        S[s]=dict(n=len(rs),j=len(J),ok=sum(1 for r in J if r.get("success")),inf=sum(1 for r in rs if r.get("failure_class") in EX),hang=sum(1 for r in rs if r.get("failure_class")=="hang"),t=[tok(r) for r in J])
    for s in ("without","with"):
        if os.path.exists(f"{R}/{pr}/{s}.incompatible.json") or os.path.exists(f"{R}/{pr}/{s}.infra.json"): S[s]["side"]="SIDE-FAIL"
    tot+=cost
    a,b=S["without"],S["with"]
    m=lambda x: f"{sum(x)/len(x):.0f}" if x else "-"
    ci=("%+.1f%% [%+.1f%%, %+.1f%%]"%tuple(100*v for v in boot(a["t"],b["t"]))) if len(a["t"])>1 and len(b["t"])>1 else "-"
    print(f"{pr} | {','.join(sorted(map(str,task)))} | {a['ok']}/{a['j']} {a.get('side','')} | {b['ok']}/{b['j']} {b.get('side','')} | {a['inf']},{b['inf']} | {a['hang']},{b['hang']} | {m(a['t'])} | {m(b['t'])} | {ci} | ${cost:.2f}")
print(f"total ${tot:.2f}")
