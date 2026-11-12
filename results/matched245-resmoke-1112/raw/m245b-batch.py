#!/usr/bin/env python3
"""PR #245 (29236b59) matched-config re-smoke: 2 harnesses x {Sonnet 5.5, Opus 5.5} x regex-chess x 1 run = 4 cells.
Sequential, one model at a time (Pi then OpenCode). Every cell passes --matched-config. Not scored.
Total cap $6 (sum of live proxy-ledger totals); guard kills the running cell and stops launching.
If any request of a model returns HTTP 400, that model's remaining cells are skipped (STOP_MODEL)."""
import json, os, subprocess, sys, threading, time, glob
REPO = os.path.expanduser("~/ob-m245b"); OUT = os.path.expanduser("~/h2/matched245-resmoke-1112")
TASK = "regex-chess"; CAP = 6.0
MODELS = os.environ.get("M245_MODELS", "claude-sonnet-5-5,claude-opus-5-5").split(",")
sys.path.insert(0, REPO)
from thesis.ab.summarize import row_cost
stop = threading.Event(); reason = []; procs = set()
def spend():
    tot = 0.0
    for f in glob.glob(f"{OUT}/cells/*/*/proxy-ledger/*.totals.json"):
        m = "claude-opus-5-5" if "opus" in f else "claude-sonnet-5-5"
        try: a = json.load(open(f))["all"]
        except Exception: continue
        tot += row_cost({"upstream_model": m, "tokens_input_uncached": a["input_uncached"], "tokens_output": a["output"],
                         "tokens_cache_read": a["cache_read"], "tokens_cache_write": a["cache_write"]}) or 0
    return tot
def log(s):
    line = time.strftime("%Y-%m-%d %H:%M:%S %Z ") + s
    print(line, flush=True); open(f"{OUT}/batch.log", "a").write(line + "\n")
def saw_400(d):
    for f in glob.glob(f"{d}/*/proxy-ledger/*.jsonl"):
        for l in open(f):
            try: r = json.loads(l)
            except Exception: continue
            if r.get("status") == 400 or r.get("upstream_status") == 400: return True
    return False
EFFORT = os.environ.get("M245_OPUS_EFFORT", "low")
def EFF(m):
    return ["--matched-effort", EFFORT] if "opus" in m else []
def run(i, h, m):
    d = f"{OUT}/cells/{i}-{h}-{m}-{TASK}"; os.makedirs(d, exist_ok=True)
    env = dict(os.environ); env["OBENCH_MATCHED_CONFIG"] = "1"
    if h == "pi":
        code = ("import importlib.util,sys;s=importlib.util.spec_from_file_location('c','data/pi-harness-smoke/cell.py');"
                f"m=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.TASK={TASK!r};sys.exit(m.main(sys.argv[1:]))")
        cmd = ["python3", "-c", code, "--out", f"{d}/pi", "--models", m, "--exec", "docker", "--image", "h1-env:1027-strace",
               "--cache", os.path.expanduser("~/h1/pi-src"), "--require-model-match", "--matched-config"] + EFF(m)
    else:
        cmd = ["python3", "data/opencode-harness-smoke/cell.py", "--out", f"{d}/opencode", "--task", TASK, "--exec", "docker",
               "--image", "h1-env:1027-strace", "--cache", os.path.expanduser("~/h1/opencode-src"), "--sha", env["OPENCODE_SHA"],
               "--node", env["OPENCODE_NODE_PREFIX"], "--vertex-model", m, "--require-model-match", "--matched-config"] + EFF(m)
    open(f"{d}/cmd.json", "w").write(json.dumps(cmd, indent=1) + "\n")
    t0 = time.time(); log(f"start {i} {h} {m} {TASK}")
    with open(f"{d}/cell.out", "w") as fh:
        p = subprocess.Popen(["timeout", "3000"] + cmd, cwd=REPO, env=env, stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)
        procs.add(p); rc = p.wait(); procs.discard(p)
    log(f"end {i} {h} {m} rc={rc} wall_s={time.time()-t0:.0f} spend=${spend():.2f}")
    return saw_400(d)
def guard():
    while not stop.is_set():
        s = spend()
        if s >= CAP:
            reason.append(f"spend ${s:.2f} >= ${CAP}"); stop.set()
            for p in list(procs):
                try: os.killpg(p.pid, 15)
                except Exception: pass
        time.sleep(10)
threading.Thread(target=guard, daemon=True).start()
log(f"launch models={MODELS} task={TASK} cap=${CAP} head={subprocess.check_output(['git','-C',REPO,'rev-parse','HEAD']).decode().strip()}")
i = 0
for m in MODELS:
    for h in ("pi", "opencode"):
        if stop.is_set(): break
        i += 1
        if run(i, h, m):
            log(f"STOP_MODEL {m}: HTTP 400 seen in cell {i}"); break
stop.set(); log(f"BATCH DONE stopped={'; '.join(reason) or 'none'} spend=${spend():.2f}")
