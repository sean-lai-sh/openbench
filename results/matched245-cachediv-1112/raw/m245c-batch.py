#!/usr/bin/env python3
"""#245 (29236b59) Pi cache-divergence smoke, A (matched, proxy edit on) then B (passthrough, matched off = #196 Pi config).
Every call: client body (before the proxy thinking/output_config edit) and forwarded body (after) saved by wrapping
thesis.ab.vertex_anthropic_proxy.apply_disabled_thinking in the cell process. The original function still runs.
OLD DOC: #245 (29236b59) Pi passthrough cache smoke: Pi x {Sonnet 5.5, Opus 5.5} x regex-chess x 1. Not scored.
OBENCH_MATCHED_CONFIG=1 stays set so Pi gets its matched 200K context and --thinking off, but the proxy's
body injection is disabled at launch time: thesis.ab.vertex_anthropic_proxy.apply_disabled_thinking is replaced
in this process by a function that writes the outgoing body (json.dumps(parsed), the exact bytes forwarded) to
<out>/pi/requests/NNNN.request.json and returns False (no edit). No repo file is changed.
Guards: total $0.90 (live ledger totals), and a cell is stopped after 10 calls or 900 s wall."""
import json, os, subprocess, sys, threading, time, glob
REPO = os.path.expanduser("~/ob-m245b"); OUT = os.path.expanduser("~/h2/matched245-cachediv-1112")
TASK = "regex-chess"; CAP = 2.20; MAX_CALLS = 12; MAX_WALL = 900; CELL_CAP = 0.55
sys.path.insert(0, REPO)
from thesis.ab.summarize import row_cost
procs = set(); stop = threading.Event(); reason = []
def spend():
    tot = 0.0
    for f in glob.glob(f"{OUT}/cells/*/*/proxy-ledger/*.jsonl"):
        if "cache-miss" in f: continue
        m = "claude-opus-5-5" if "opus" in f else "claude-sonnet-5-5"
        for l in open(f):
            try: a = json.loads(l)
            except Exception: continue
            tot += row_cost({"upstream_model": m, "tokens_input_uncached": a.get("input_uncached") or 0, "tokens_output": a.get("output") or 0,
                             "tokens_cache_read": a.get("cache_read") or 0, "tokens_cache_write": a.get("cache_write") or 0}) or 0
    return tot
def calls(d):
    n = 0
    for f in glob.glob(f"{d}/*/proxy-ledger/*.jsonl"):
        if "cache-miss" in f: continue
        n += sum(1 for l in open(f) if l.strip())
    return n
def log(s):
    line = time.strftime("%Y-%m-%d %H:%M:%S %Z ") + s
    print(line, flush=True); open(f"{OUT}/batch.log", "a").write(line + "\n")
def kill_my_containers():
    ids = subprocess.run(["docker", "ps", "-q"], capture_output=True, text=True).stdout.split()
    for c in ids:
        m = subprocess.run(["docker", "inspect", "-f", "{{range .Mounts}}{{.Source}} {{end}}", c], capture_output=True, text=True).stdout
        if f"{os.path.expanduser('~')}/ob-m245b/" in m:
            subprocess.run(["docker", "kill", c], capture_output=True); log(f"docker kill {c}")
CAPTURE = r'''
import importlib.util,sys,os,json,threading
import thesis.ab.vertex_anthropic_proxy as v
_d=os.path.join(sys.argv[sys.argv.index("--out")+1],"requests"); os.makedirs(_d,exist_ok=True); _n=[0]; _l=threading.Lock()
_orig=v.apply_disabled_thinking
def _capture(data, model=None):
    with _l:
        _n[0]+=1; k=_n[0]
        open(os.path.join(_d,"%%04d.client.json"%%k),"w",encoding="utf-8").write(json.dumps(data))
        changed=_orig(data, model)
        open(os.path.join(_d,"%%04d.forwarded.json"%%k),"w",encoding="utf-8").write(json.dumps(data))
        open(os.path.join(_d,"%%04d.meta.json"%%k),"w").write(json.dumps({"changed":bool(changed),"model":model}))
    return changed
v.apply_disabled_thinking=_capture
s=importlib.util.spec_from_file_location("c","data/pi-harness-smoke/cell.py");m=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.TASK=%r
sys.exit(m.main(sys.argv[1:]))
'''
def cell_spend(d, m):
    tot = 0.0
    for f in glob.glob(f"{d}/*/proxy-ledger/*.jsonl"):
        if "cache-miss" in f: continue
        for l in open(f):
            try: a = json.loads(l)
            except Exception: continue
            tot += row_cost({"upstream_model": m, "tokens_input_uncached": a.get("input_uncached") or 0, "tokens_output": a.get("output") or 0,
                             "tokens_cache_read": a.get("cache_read") or 0, "tokens_cache_write": a.get("cache_write") or 0}) or 0
    return tot
def run(i, arm, m):
    d = f"{OUT}/cells/{i}-{arm}-pi-{m}-{TASK}"; os.makedirs(d, exist_ok=True)
    env = dict(os.environ); env.pop("OBENCH_MATCHED_CONFIG", None); env.pop("OBENCH_MATCHED_EFFORT", None)
    extra = []
    if arm == "A":
        env["OBENCH_MATCHED_CONFIG"] = "1"; extra = ["--matched-config"] + (["--matched-effort", "low"] if "opus" in m else [])
    cmd = ["python3", "-c", CAPTURE % TASK, "--out", f"{d}/pi", "--models", m, "--exec", "docker", "--image", "h1-env:1027-strace",
           "--cache", os.path.expanduser("~/h1/pi-src"), "--require-model-match"] + extra
    open(f"{d}/cmd.json", "w").write(json.dumps(cmd, indent=1) + "\n")
    t0 = time.time(); log(f"start {i} {arm} pi {m} {TASK} {extra}")
    with open(f"{d}/cell.out", "w") as fh:
        p = subprocess.Popen(["timeout", "3000"] + cmd, cwd=REPO, env=env, stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)
        procs.add(p)
        while p.poll() is None:
            why = None
            if calls(d) >= MAX_CALLS: why = f"calls>={MAX_CALLS}"
            elif time.time() - t0 > MAX_WALL: why = f"wall>{MAX_WALL}s"
            elif cell_spend(d, m) >= CELL_CAP: why = f"cell spend>={CELL_CAP}"
            elif spend() >= CAP: why = f"spend>={CAP}"; stop.set()
            if why:
                log(f"stopping cell {i}: {why}")
                try: os.killpg(p.pid, 15)
                except Exception: pass
                time.sleep(5); kill_my_containers(); break
            time.sleep(5)
        rc = p.wait(); procs.discard(p)
    log(f"end {i} {arm} pi {m} rc={rc} calls={calls(d)} wall_s={time.time()-t0:.0f} spend=${spend():.3f}")
log(f"launch cachediv A+B task={TASK} cap=${CAP} head={subprocess.check_output(['git','-C',REPO,'rev-parse','HEAD']).decode().strip()}")
for i, (arm, m) in enumerate([("A","claude-sonnet-5-5"),("A","claude-opus-5-5"),("B","claude-sonnet-5-5"),("B","claude-opus-5-5")], 1):
    if stop.is_set(): break
    run(i, arm, m)
log(f"BATCH DONE spend=${spend():.3f}")
