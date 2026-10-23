"""H2 per-row x task summary. Status from an_a2.py rescore-A2.csv (blocked/env_failure/solved/fail);
tokens = input_uncached + output + cache_read + cache_write from each cell JSON. Blocked + env_failure excluded from
pass rate and token analysis (A2). Token effect per pre-reg: 95% bootstrap CI (10k, seed 0) of mean-ratio change excludes 0
AND point outside the model's A/A band. Compute cost per cell = VM $/h * wall / mean(concurrency at start,end).
usage: python3 h2sum.py <byrow_dir> <vm_usd_per_h>"""
import csv,json,glob,sys,os,random,statistics as st,collections,math
B=sys.argv[1]; RATE=float(sys.argv[2])
BAND={"sonnet":(-6.5,6.8),"opus":(-10.4,4.4)}
A2={}
for r in csv.DictReader(open(f"{B}/rescore-A2.csv")): A2[(r["batch"],r["side"],r["task"],r["trial"])]=r["status_a2"]
from datetime import datetime
cells=[]
for f in sorted(glob.glob(f"{B}/*/*/cells/*/*/*.json")):
    p=f.split("/"); batch,pr,side,task,trial=p[-6],p[-5],p[-3],p[-2],os.path.splitext(p[-1])[0]
    r=json.load(open(f)); tok=sum((r.get(k) or 0) for k in ("tokens_input_uncached","tokens_output","tokens_cache_read","tokens_cache_write"))
    s,e=r.get("started_et"),r.get("ended_et")
    wall=(datetime.fromisoformat(e)-datetime.fromisoformat(s)).total_seconds() if s and e else 0
    cc=max(1,((r.get("concurrent_at_start") or 1)+(r.get("concurrent_at_end") or 1))/2)
    cells.append(dict(model=batch.split("-")[0],pr=pr,row=batch,side=side,task=task,trial=trial,status=A2.get((batch,side,task,trial),"?"),
        failure_class=r.get("failure_class"),hang=r.get("failure_class") in("timeout","hang","no_progress","stalled") ,tokens_total=tok,
        model_cost_usd=round(r.get("requests_cost_usd") or 0,4),compute_cost_usd=round(RATE*wall/3600/cc,4),wall_s=round(wall,1),
        started_et=s,ended_et=e,concurrent_at_start=r.get("concurrent_at_start"),concurrent_at_end=r.get("concurrent_at_end"),
        vm_type=r.get("vm_type"),runner_commit=r.get("runner_commit"),prereg_sha256="a8668fc6641bc9eeb855065688fbbc02a0d3754c0021013e5169b4b0b0b88814"))
w=csv.DictWriter(open(f"{B}/cells-h2.csv","w"),fieldnames=list(cells[0])); w.writeheader(); w.writerows(cells)
def boot(a,b):
    rng=random.Random(0); v=[]
    for _ in range(10000):
        x=[rng.choice(a) for _ in a]; y=[rng.choice(b) for _ in b]; v.append((st.mean(y)/st.mean(x)-1)*100)
    v.sort(); return v[249],v[9749]
out=["H2 hard suite, pre-reg v2+A1+A2 sha256 a8668fc6641bc9eeb855065688fbbc02a0d3754c0021013e5169b4b0b0b88814",
 "row | task | solved/N without | solved/N with | blocked wo/w | env wo/w | hangs wo/w | tokens mean wo -> w | change % [95% CI] | effect | completed-only change % | Fisher p (only if pooled 2..8/10)"]
G=collections.defaultdict(list)
for c in cells: G[(c["row"],c["task"])].append(c)
def fisher(a,n1,b,n2):
    from math import comb
    K=a+b; N=n1+n2; pobs=comb(n1,a)*comb(n2,b)/comb(N,K)
    return sum(comb(n1,i)*comb(N-n1,K-i)/comb(N,K) for i in range(max(0,K-n2),min(K,n1)+1) if comb(n1,i)*comb(N-n1,K-i)/comb(N,K)<=pobs*(1+1e-9))
eff=[]
for (row,task),cs in sorted(G.items()):
    m=row.split("-")[0]; S={}
    for sd in("without","with"):
        x=[c for c in cs if c["side"]==sd]; sc=[c for c in x if c["status"] in("solved","fail")]
        S[sd]=dict(sol=sum(c["status"]=="solved" for c in sc),n=len(sc),blk=sum(c["status"]=="blocked" for c in x),env=sum(c["status"]=="env_failure" for c in x),
                   hang=sum(c["hang"] for c in x),tok=[c["tokens_total"] for c in sc],tokc=[c["tokens_total"] for c in sc if c["status"]=="solved"])
    a,b=S["without"],S["with"]; ch=ci=e="n/a"; cc="n/a"; fp=""
    if len(a["tok"])>=2 and len(b["tok"])>=2 and st.mean(a["tok"])>0:
        pt=(st.mean(b["tok"])/st.mean(a["tok"])-1)*100; lo,hi=boot(a["tok"],b["tok"])
        lo_b,hi_b=BAND[m]; e="EFFECT" if (lo>0 or hi<0) and not(lo_b<=pt<=hi_b) else "-"
        if e=="EFFECT": eff.append((row,task,round(pt,1)))
        ch=f"{pt:+.1f}"; ci=f"[{lo:+.1f},{hi:+.1f}]"
    if len(a["tokc"])>=1 and len(b["tokc"])>=1: cc=f"{(st.mean(b['tokc'])/st.mean(a['tokc'])-1)*100:+.1f}"
    if a["n"] and b["n"] and all(2<=s["sol"]*10/max(s["n"],1)<=8 for s in (a,b)): fp=f"{fisher(a['sol'],a['n'],b['sol'],b['n']):.3f}"
    out.append(f"{row} | {task} | {a['sol']}/{a['n']} | {b['sol']}/{b['n']} | {a['blk']}/{b['blk']} | {a['env']}/{b['env']} | {a['hang']}/{b['hang']} | "
               f"{(round(st.mean(a['tok'])) if a['tok'] else 'n/a')} -> {(round(st.mean(b['tok'])) if b['tok'] else 'n/a')} | {ch} {ci} | {e} | {cc} | {fp}")
out.append("== token effects (CI excl 0 and outside band): "+(", ".join(f"{r}/{t} {p:+.1f}%" for r,t,p in eff) or "none"))
for m in("sonnet","opus"):
    x=[c for c in cells if c["model"]==m]
    for sd in("without","with"):
        y=[c for c in x if c["side"]==sd]; sc=[c for c in y if c["status"] in("solved","fail")]
        out.append(f"== {m} {sd}: cells {len(y)}, pass {sum(c['status']=='solved' for c in sc)}/{len(sc)}, blocked {sum(c['status']=='blocked' for c in y)}, env {sum(c['status']=='env_failure' for c in y)}, hangs {sum(c['hang'] for c in y)}, model ${sum(c['model_cost_usd'] for c in y):.2f}, compute ${sum(c['compute_cost_usd'] for c in y):.2f}")
out.append(f"== TOTAL cells {len(cells)} model ${sum(c['model_cost_usd'] for c in cells):.2f} compute(alloc) ${sum(c['compute_cost_usd'] for c in cells):.2f} @ ${RATE}/h")
open(f"{B}/SUMMARY-H2.txt","w").write("\n".join(out)+"\n"); print("\n".join(out))
