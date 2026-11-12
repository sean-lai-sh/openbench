import json,glob,os,sys
sys.path.insert(0, os.path.expanduser("~/ob-m245b"))
from thesis.ab.summarize import row_cost
B=os.path.expanduser("~/h2/matched245-resmoke-1112")
out={"cells":[]}
for d in sorted(glob.glob(B+"/cells/*")):
    name=os.path.basename(d); arm=name.split("-")[1]; model="claude-opus-5-5" if "opus" in name else "claude-sonnet-5-5"
    rec=json.load(open(glob.glob(f"{d}/{arm}/claude-*.json")[0])); row=rec.get("row") or {}
    led=[f for f in glob.glob(f"{d}/{arm}/proxy-ledger/*.jsonl") if "cache-miss" not in f]
    rows=[json.loads(l) for f in led for l in open(f) if l.strip()]
    tot=None
    for f in glob.glob(f"{d}/{arm}/proxy-ledger/*.totals.json"):
        a=json.load(open(f))["all"]; tot=a
    cost=row_cost({"upstream_model":model,"tokens_input_uncached":tot["input_uncached"],"tokens_output":tot["output"],"tokens_cache_read":tot["cache_read"],"tokens_cache_write":tot["cache_write"]}) if tot else 0.0
    tr=open(glob.glob(f"{d}/{arm}/transcripts/*/*.txt")[0],errors="replace").read()
    c={"cell":name,"arm":arm,"model":model,"cell_id":rec.get("cell_id"),
       "proxy_requests":rec.get("proxy_requests"),"trace_requests":rec.get("trace_requests"),"untraced_requests":rec.get("untraced_requests"),
       "ledger_rows":len(rows),"statuses":sorted({r.get("status") for r in rows}) ,"upstream_models":sorted({str(r.get("upstream_model")) for r in rows}),
       "thinking_json_set":sorted({str(r.get("thinking_json")) for r in rows}),"output_config_json_set":sorted({str(r.get("output_config_json")) for r in rows}),
       "thinking_sent_set":sorted({str(r.get("thinking_sent")) for r in rows}),
       "thinking_tokens":[r.get("thinking_tokens") for r in rows],"cache_read":[r.get("cache_read") for r in rows],"cache_write":[r.get("cache_write") for r in rows],
       "output":[r.get("output") for r in rows],"call_roles":sorted({str(r.get("call_role")) for r in rows}),
       "completed":row.get("completed"),"failure_class":row.get("failure_class"),"checker_exit":row.get("checker_exit"),
       "checker_stderr":(row.get("checker_stderr") or "")[:200],"wall_s":row.get("wall_time_s") or row.get("t_agent_s"),
       "model_context_window":row.get("model_context_window"),"settings":rec.get("settings"),"cost_usd":round(cost,4),"totals":tot,
       "transcript_error":[l[:300] for l in tr.splitlines() if '"type":"error"' in l][:3],
       "thinkingLevel_in_transcript":sorted(set(__import__("re").findall(r'"thinkingLevel":"(\w+)"',tr)))}
    out["cells"].append(c)
out["spend_cells_usd"]=round(sum(c["cost_usd"] for c in out["cells"]),4)
pr=[json.load(open(f)) for f in sorted(glob.glob(B+"/opus-effort-probe/probe-*.json")) if "summary" not in f]
out["probe"]=[{"effort":p["effort"],"status":p["status"],"body":p["response_body"],"ledger":[{k:r.get(k) for k in ("status","thinking_json","output_config_json","thinking_sent","thinking_tokens","input_uncached","output","cache_read","cache_write")} for r in p["ledger_rows"]]} for p in pr]
json.dump(out,open(B+"/analysis.json","w"),indent=1)
for c in out["cells"]:
    print(json.dumps({k:v for k,v in c.items()}))
print(json.dumps(out["probe"])); print("spend",out["spend_cells_usd"])
