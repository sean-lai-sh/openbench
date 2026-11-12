#!/usr/bin/env python3
"""#245 (29236b59) Pi passthrough cache smoke: Pi x {Sonnet 5.5, Opus 5.5} x regex-chess x 1. Not scored.
OBENCH_MATCHED_CONFIG=1 stays set so Pi gets its matched 200K context and --thinking off, but the proxy's
body injection is disabled at launch time: thesis.ab.vertex_anthropic_proxy.apply_disabled_thinking is replaced
in this process by a function that writes the outgoing body (json.dumps(parsed), the exact bytes forwarded) to
<out>/pi/requests/NNNN.request.json and returns False (no edit). No repo file is changed.
Guards: total $0.90 (live ledger totals), and a cell is stopped after 10 calls or 900 s wall."""
import json, os, subprocess, sys, threading, time, glob
REPO = os.path.expanduser("~/ob-m245b"); OUT = os.path.expanduser("~/h2/matched245-passthrough-1112")
TASK = "regex-chess"; CAP = 0.90; MAX_CALLS = 10; MAX_WALL = 900
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
def _capture(data, model=None):
    with _l:
        _n[0]+=1; open(os.path.join(_d,"%%04d.request.json"%%_n[0]),"w",encoding="utf-8").write(json.dumps(data))
    return False
v.apply_disabled_thinking=_capture
s=importlib.util.spec_from_file_location("c","data/pi-harness-smoke/cell.py");m=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.TASK=%r
sys.exit(m.main(sys.argv[1:]))
'''
def run(i, m):
    d = f"{OUT}/cells/{i}-pi-{m}-{TASK}"; os.makedirs(d, exist_ok=True)
    env = dict(os.environ); env["OBENCH_MATCHED_CONFIG"] = "1"; env.pop("OBENCH_MATCHED_EFFORT", None)
    cmd = ["python3", "-c", CAPTURE % TASK, "--out", f"{d}/pi", "--models", m, "--exec", "docker", "--image", "h1-env:1027-strace",
           "--cache", os.path.expanduser("~/h1/pi-src"), "--require-model-match", "--matched-config"]
    open(f"{d}/cmd.json", "w").write(json.dumps(cmd, indent=1) + "\n")
    t0 = time.time(); log(f"start {i} pi {m} {TASK}")
    with open(f"{d}/cell.out", "w") as fh:
        p = subprocess.Popen(["timeout", "3000"] + cmd, cwd=REPO, env=env, stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)
        procs.add(p)
        while p.poll() is None:
            why = None
            if calls(d) >= MAX_CALLS: why = f"calls>={MAX_CALLS}"
            elif time.time() - t0 > MAX_WALL: why = f"wall>{MAX_WALL}s"
            elif spend() >= CAP: why = f"spend>={CAP}"; stop.set()
            if why:
                log(f"stopping cell {i}: {why}")
                try: os.killpg(p.pid, 15)
                except Exception: pass
                time.sleep(5); kill_my_containers(); break
            time.sleep(5)
        rc = p.wait(); procs.discard(p)
    log(f"end {i} pi {m} rc={rc} calls={calls(d)} wall_s={time.time()-t0:.0f} spend=${spend():.3f}")
log(f"launch passthrough task={TASK} cap=${CAP} head={subprocess.check_output(['git','-C',REPO,'rev-parse','HEAD']).decode().strip()}")
for i, m in enumerate(["claude-sonnet-5-5", "claude-opus-5-5"], 1):
    if stop.is_set(): break
    run(i, m)
log(f"BATCH DONE spend=${spend():.3f}")
