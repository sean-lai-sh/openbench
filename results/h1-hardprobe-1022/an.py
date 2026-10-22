import json,glob,sys,csv,collections
sys.path.insert(0,"/ob")
from thesis.ab.summarize import row_cost
R="/h1/h1-hardprobe-1022"
rows=[]
for d in ("sonnet","opus","sonnet-rerun","opus-rerun"):
    for f in sorted(glob.glob(f"{R}/{d}/*/cells/*/*/*.json")):
        r=json.load(open(f)); p=f.split("/")
        env_fail = r.get("checker_exit")=="timeout"
        rows.append(dict(model=d.split("-")[0],batch=d,side=p[-3],task=p[-2],failure_class=r.get("failure_class"),
          scored=not env_fail, solved=r.get("failure_class")=="solved",
          upstream_model=r.get("upstream_model"),tokens_output=r.get("tokens_output"),tokens_input_uncached=r.get("tokens_input_uncached"),
          tokens_cache_read=r.get("tokens_cache_read"),tokens_cache_write=r.get("tokens_cache_write"),t_agent_s=r.get("t_agent_s"),
          t_checker_s=r.get("t_checker_s"),checker_exit=r.get("checker_exit"),
          cost_usd=round(row_cost(r) or 0,4),started_et=r.get("started_et"),ended_et=r.get("ended_et"),
          concurrent_at_start=r.get("concurrent_cells_at_start"),concurrent_at_end=r.get("concurrent_cells_at_end"),
          vm_type=r.get("vm_type"),runner_commit=r.get("runner_commit"),timeout_cap_s=r.get("timeout_cap_s") or r.get("timeout_s")))
cols=list(rows[0])
w=csv.DictWriter(open(f"{R}/cells.csv","w"),fieldnames=cols);w.writeheader();w.writerows(rows)
with open(f"{R}/cells-concurrency.csv","w") as fh:
    c=csv.writer(fh);k=("model","batch","side","task","started_et","ended_et","concurrent_at_start","concurrent_at_end");c.writerow(k)
    for r in sorted(rows,key=lambda r:r["started_et"] or ""):c.writerow([r[x] for x in k])
out=[]
for m in ("sonnet","opus"):
    s=[r for r in rows if r["model"]==m and r["scored"]]
    out.append(f"== {m}: scored {len(s)} cells, solved {sum(r['solved'] for r in s)}, hangs {sum(r['failure_class']=='hang' for r in s)}, agent-cap timeouts {sum(r['failure_class']=='timeout' for r in s)}, model cost ${sum(r['cost_usd'] for r in s):.2f} (${sum(r['cost_usd'] for r in s)/max(len(s),1):.3f}/cell)")
    for t in sorted({r['task'] for r in s}):
        ts=[r for r in s if r['task']==t]
        out.append(f"  {t:32s} {sum(r['solved'] for r in ts)}/{len(ts)}  out_tok={[r['tokens_output'] for r in ts]} classes={[r['failure_class'] for r in ts]} cost=${sum(r['cost_usd'] for r in ts):.2f}")
ex=[r for r in rows if not r["scored"]]
out.append(f"== env failures (unscored, rerun): {len(ex)} cells, model cost ${sum(r['cost_usd'] for r in ex):.2f}: "+", ".join(f"{r['model']}/{r['side']}/{r['task']}" for r in ex))
out.append(f"== total model spend incl. env failures: ${sum(r['cost_usd'] for r in rows):.2f}; upstream_models={dict(collections.Counter((r['model'],r['upstream_model']) for r in rows))}")
open(f"{R}/SUMMARY-H1.txt","w").write("\n".join(out)+"\n"); print("\n".join(out))
