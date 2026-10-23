"""H2 per-row / per-task tables from rescore-A2.csv (an_a2.py output) + cell JSON failure_class.
Columns: solved, fail(wrong_answer/hang/2400s-timeout -> fail per A2), blocked, env_failure (checker timeout, unscored),
infra (infra + incompatible; an_a2 counts these as fail -- shown separately, and pass_rate_excl_infra excludes them)."""
import csv,json,glob,collections,sys,os
R=sys.argv[1]
rows=list(csv.DictReader(open(f"{R}/rescore-A2/rescore-A2.csv")))
# rescore csv has no PR column; recover from cell paths in the same sort order an_a2 used
paths=[]
for d in ["sonnet","opus"]:
    paths+=sorted(glob.glob(f"{R}/{d}/*/cells/*/*/*.json"))
assert len(paths)==len(rows)
for r,p in zip(rows,paths):
    pp=p.split("/"); assert (pp[-3],pp[-2],os.path.splitext(pp[-1])[0])==(r["side"],r["task"],r["trial"])
    r["pr"]=pp[-5]
CTRL={"2533","913","11731"}
def cls(r):
    s=r["status_a2"]
    if s=="fail" and r["failure_class_orig"] in("infra","incompatible"): return "infra"
    return s
def agg(sel):
    c=collections.Counter(cls(r) for r in sel)
    sol=c["solved"]; fail=c["fail"]; inf=c["infra"]
    a2den=sol+fail+inf
    return dict(cells=len(sel),solved=sol,fail=fail,blocked=c["blocked"],env_failure=c["env_failure"],infra=inf,
        pass_rate_A2=f"{sol/a2den:.1%}" if a2den else "n/a",
        pass_rate_excl_infra=f"{sol/(sol+fail):.1%}" if sol+fail else "n/a",
        cost_usd=round(sum(float(r["cost_usd"]) for r in sel),2))
out=[]
order=lambda m,pr:(m!="sonnet",pr in CTRL,int(pr))
keys=sorted({(r["model"],r["pr"]) for r in rows},key=lambda k:order(*k))
W=csv.writer(open(f"{R}/rescore-A2/per-row-A2.csv","w"))
hdr=["model","pr","role","side","cells","solved","fail","blocked","env_failure","infra","pass_rate_A2","pass_rate_excl_infra","cost_usd","early_stop"]
W.writerow(hdr); out.append("\t".join(hdr))
for m,pr in keys:
    es=os.path.exists(f"{R}/{m}/{pr}/early-stop.json")
    for side in ("with","without","ALL"):
        sel=[r for r in rows if r["model"]==m and r["pr"]==pr and (side=="ALL" or r["side"]==side)]
        a=agg(sel); line=[m,pr,"control" if pr in CTRL and m=="sonnet" else "signal",side]+[a[k] for k in hdr[4:13]]+["infra-early-stop" if es else ""]
        W.writerow(line); out.append("\t".join(map(str,line)))
W=csv.writer(open(f"{R}/rescore-A2/per-task-A2.csv","w"))
hdr2=["model","task","side","rows_measured","cells","solved","fail","blocked","env_failure","infra","pass_rate_A2","pass_rate_excl_infra"]
W.writerow(hdr2); out.append(""); out.append("per-task (measured rows only, i.e. excluding PR rows that infra-early-stopped)"); out.append("\t".join(hdr2))
for m in ("sonnet","opus"):
    meas=[pr for (mm,pr) in keys if mm==m and not os.path.exists(f"{R}/{m}/{pr}/early-stop.json")]
    for t in sorted({r["task"] for r in rows}):
        for side in ("with","without"):
            sel=[r for r in rows if r["model"]==m and r["pr"] in meas and r["task"]==t and r["side"]==side]
            a=agg(sel); line=[m,t,side,"+".join(meas)]+[a[k] for k in hdr2[4:]]
            W.writerow(line); out.append("\t".join(map(str,line)))
out.append("")
for m in ("sonnet","opus"):
    a=agg([r for r in rows if r["model"]==m]); out.append(f"TOTAL {m}: "+json.dumps(a))
# proxy ledger spend (Vertex list prices from thesis/ab/summarize.py RATES_BY_MODEL; cache write at 5m rate)
P={"claude-opus-5-5":(4.0,20.0,0.20,5.0),"claude-sonnet-5-5":(2.0,10.0,0.10,2.5)}
def ledger(d):
    tot=collections.Counter(); n=collections.Counter(); h1=0
    for f in glob.glob(f"{d}/proxy-ledger/*.jsonl"):
        for l in open(f):
            if not l.strip(): continue
            e=json.loads(l)
            if e.get("record_type")!="request": continue
            u=e.get("usage") or {}; m=(e.get("upstream_model") or "claude-opus-5-5").split("@")[0]; p=P.get(m,P["claude-opus-5-5"])
            h1+=((u.get("cache_creation") or {}).get("ephemeral_1h_input_tokens") or 0)
            tot[m]+=(u.get("input_tokens",0)*p[0]+u.get("output_tokens",0)*p[1]+u.get("cache_read_input_tokens",0)*p[2]+u.get("cache_creation_input_tokens",0)*p[3])/1e6; n[m]+=1
    return {k:round(v,2) for k,v in tot.items()},dict(n),h1
for d in (f"{R}/sonnet",f"{R}/opus",f"{R}/../h2-deferred-opus-attempt1"):
    out.append(f"LEDGER {os.path.normpath(d)}: usd={ledger(d)[0]} requests={ledger(d)[1]} 1h_cache_write_tokens={ledger(d)[2]}")
open(f"{R}/rescore-A2/TABLES-H2-A2.txt","w").write("\n".join(out)+"\n")
print("\n".join(out))
