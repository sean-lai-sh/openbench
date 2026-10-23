"""H1/H2 scorer with pre-reg Amendment A2 'blocked' status
(hard-suite-prereg-v2.md sha256 a8668fc6641bc9eeb855065688fbbc02a0d3754c0021013e5169b4b0b0b88814).
blocked = the provider refused via its content filter. Detected only from machine records, never by hand:
  - an OpenCode event {"type":"error","error":{"name":"ContentFilterError"}} in the cell's agent-output.txt / cell output_tail, or
  - a provider stop_reason/finish_reason of 'refusal' / 'content_filter' in the cell JSON.
blocked cells are counted per side and excluded from the pass-rate denominator (like infra/env cells).
Writes rescore-A2.csv + SUMMARY-A2.txt + BLOCKED-EVIDENCE-A2.txt; never touches cells.csv.
usage: python3 an_a2.py <results_dir> [batch ...]"""
import json,glob,sys,csv,os,re,collections
R=sys.argv[1]; BATCHES=sys.argv[2:] or ["sonnet","opus","sonnet-rerun","opus-rerun"]
REFUSAL_STOPS={"refusal","content_filter","content-filter","safety"}
def cost(r):
    c=r.get("requests_cost_usd")
    return round(c,4) if isinstance(c,(int,float)) else 0.0
def events(text):
    for line in text.splitlines():
        line=line.strip()
        if line.startswith("{") and '"type"' in line:
            try: yield json.loads(line)
            except Exception: pass
        for m in re.finditer(r'\{"type":"error".*?\}\}\}',line):
            try: yield json.loads(m.group(0))
            except Exception: pass
def blocked_reason(r,cellfile):
    for k in ("stop_reason","finish_reason","provider_stop_reason"):
        if str(r.get(k) or "").lower() in REFUSAL_STOPS: return f"{k}={r.get(k)}",""
    p=cellfile.split("/"); trial=os.path.splitext(p[-1])[0]
    tr=os.path.join(*["/"]+p[:-4],"transcripts",p[-3],p[-2],trial,"agent-output.txt")
    srcs=[("output_tail",r.get("output_tail") or "")]
    if os.path.exists(tr): srcs.append((tr,open(tr,errors="replace").read()))
    for src,txt in srcs:
        for e in events(txt):
            err=e.get("error") if isinstance(e,dict) else None
            if e.get("type")=="error" and isinstance(err,dict) and err.get("name")=="ContentFilterError":
                return "ContentFilterError", f"{src}: {json.dumps(e)[:300]}"
    return None,""
rows=[];ev=[]
for d in BATCHES:
    for f in sorted(glob.glob(f"{R}/{d}/*/cells/*/*/*.json")):
        r=json.load(open(f)); p=f.split("/")
        env_fail=r.get("checker_exit")=="timeout"
        br,evid=blocked_reason(r,os.path.abspath(f))
        status="env_failure" if env_fail else ("blocked" if br else ("solved" if r.get("failure_class")=="solved" else "fail"))
        if br: ev.append(f"{d}/{p[-3]}/{p[-2]}/{p[-1]}: {br} | {evid}")
        rows.append(dict(model=d.split("-")[0],batch=d,side=p[-3],task=p[-2],trial=os.path.splitext(p[-1])[0],
            status_a2=status,failure_class_orig=r.get("failure_class"),blocked_reason=br or "",
            in_pass_denominator=status in("solved","fail"),solved=status=="solved",
            tokens_output=r.get("tokens_output"),requests_count=r.get("requests_count"),cost_usd=cost(r),
            started_et=r.get("started_et"),ended_et=r.get("ended_et"),runner_commit=r.get("runner_commit")))
os.makedirs(R,exist_ok=True)
w=csv.DictWriter(open(f"{R}/rescore-A2.csv","w"),fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
out=["H1 rescore under pre-reg v2+A1+A2 (sha256 a8668fc6641bc9eeb855065688fbbc02a0d3754c0021013e5169b4b0b0b88814) by an_a2.py; cells.csv untouched.",
     "pass rate = solved / (solved + fail); blocked and env_failure excluded from denominator."]
for m in sorted({r["model"] for r in rows},key=lambda x:(x!="sonnet",x)):
    for side in sorted({r["side"] for r in rows if r["model"]==m})+["ALL"]:
        s=[r for r in rows if r["model"]==m and (side=="ALL" or r["side"]==side)]
        den=[r for r in s if r["in_pass_denominator"]]; sol=sum(r["solved"] for r in den)
        out.append(f"== {m} {side}: pass {sol}/{len(den)} = {sol/max(len(den),1):.1%}; blocked {sum(r['status_a2']=='blocked' for r in s)}; env_failure (unscored) {sum(r['status_a2']=='env_failure' for r in s)}")
out.append("== blocked cells: "+("; ".join(f"{r['model']}/{r['side']}/{r['task']} ({r['blocked_reason']}, orig {r['failure_class_orig']})" for r in rows if r["status_a2"]=="blocked") or "none"))
open(f"{R}/SUMMARY-A2.txt","w").write("\n".join(out)+"\n")
open(f"{R}/BLOCKED-EVIDENCE-A2.txt","w").write("\n".join(ev)+"\n")
print("\n".join(out))
