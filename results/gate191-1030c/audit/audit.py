import json,os,sys,csv
from datetime import datetime,timedelta
base=os.path.expanduser("~/wt-pvo/results")
sets={"#196 pi-vs-oc-180-1029":"pi-vs-oc-180-1029","#135 h2-deferred-26821-1024":"h2-deferred-26821-1024","H2 h2-hardsuite-1022":"h2-hardsuite-1022"}
rows=[]
import re
def pr_of(p):
    m=re.search(r"/(?:opus|sonnet)/(\d+)/",p); return m.group(1) if m else ""
def side_of(p):
    m=re.search(r"/(with|without)(?:\.jsonl|/)",p); return m.group(1) if m else (os.path.basename(os.path.dirname(p)) if "cells/" in p else "")
for label,d in sets.items():
    seen=set()
    for root,_,files in os.walk(os.path.join(base,d)):
        if "proxy-ledger" in root: continue
        for fn in files:
            p=os.path.join(root,fn)
            if not fn.endswith((".jsonl",".json")): continue
            try: txt=open(p,errors="replace").read()
            except OSError: continue
            recs=[]
            if fn.endswith(".jsonl"):
                for l in txt.splitlines():
                    try: recs.append(json.loads(l))
                    except: pass
            else:
                try: recs=[json.loads(txt)]
                except: pass
            for r in recs:
                if isinstance(r,dict) and isinstance(r.get("row"),dict): r={**r["row"],"requests_cost_usd":r.get("requests_cost_usd") or r["row"].get("requests_cost_usd")}
                if not isinstance(r,dict) or "task" not in r or "t_checker_s" not in r: continue
                key=(r.get("run_id"),r.get("started_et"),r.get("ts_iso"),r.get("pr"),r.get("side"))
                if key in seen: continue
                seen.add(key)
                blob=str(r.get("checker_stdout",""))+str(r.get("checker_stderr",""))+str(r.get("error",""))
                end=r.get("ended_et")
                try: e=datetime.fromisoformat(end); s=e-timedelta(seconds=float(r.get("t_checker_s") or 0))
                except Exception: e=s=None
                rows.append(dict(set=label,file=os.path.relpath(p,base),run_id=r.get("run_id"),pr=r.get("pr") or pr_of(p),side=r.get("side") or side_of(p),cost=r.get("requests_cost_usd") if r.get("requests_cost_usd") is not None else r.get("proxy_cost_usd"),harness=r.get("harness"),task=r["task"],
                    trial=r.get("trial"),checker_exit=r.get("checker_exit"),t_checker_s=r.get("t_checker_s"),
                    eaddrinuse="EADDRINUSE" in blob or "Address already in use" in blob,
                    timeout=str(r.get("checker_exit"))=="timeout",chk_start=s,chk_end=e))
torch=[r for r in rows if r["task"].startswith("torch-")]
for r in torch:
    r["overlap_with"]=""
    if r["chk_start"] is None: continue
    o=[x for x in torch if x is not r and x["set"]==r["set"] and x["chk_start"] and x["chk_start"]<r["chk_end"] and r["chk_start"]<x["chk_end"]]
    r["overlap_n"]=len(o)
    r["overlap_with"]=";".join(f'{x["pr"]}/{x["side"]}/{x["task"]}/t{x["trial"]}' for x in o)
cols=["set","harness","pr","side","task","trial","run_id","checker_exit","t_checker_s","cost","eaddrinuse","timeout","chk_start","chk_end","overlap_with","file"]
w=csv.DictWriter(open("/tmp/collision-audit.csv","w"),fieldnames=cols,extrasaction="ignore");w.writeheader()
for r in torch: w.writerow(r)
for label in sets:
    T=[r for r in torch if r["set"]==label]; A=[r for r in rows if r["set"]==label]
    ea=[r for r in A if r["eaddrinuse"]]
    to=[r for r in T if r["timeout"]]; too=[r for r in to if r["overlap_with"]]
    print(label,"rows",len(A),"torch",len(T),"EADDRINUSE",len(ea),"(torch",sum(r["task"].startswith("torch-") for r in ea),") torch_timeouts",len(to),"timeouts_overlapping",len(too),"torch_overlapping",sum(1 for r in T if r["overlap_with"]))
    for r in ea+[r for r in too if not r["eaddrinuse"]]: print("  ",r["pr"],r["side"],r["task"],"t",r["trial"],r["checker_exit"],r["t_checker_s"],"EADDR" if r["eaddrinuse"] else "","TO" if r["timeout"] else "","ovl:",r["overlap_with"][:80])

import collections
c=collections.defaultdict(list)
for r in rows:
    if r["task"]=="torch-pipeline-parallelism" and r["set"].startswith("H2"): c[(r["pr"],r["side"])].append(r["cost"])
for k,v in sorted(c.items()): print("TPP",k,len(v),v)
