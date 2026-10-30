#!/usr/bin/env python3
"""Pi vs OpenCode batch: 2 harnesses x Sonnet 5.5 x 9 tb-hard tasks x 10 runs = 180 cells.
Order: seeded shuffle random.Random(20261024) (prereg s6). Each cell = one run of the
committed gate cell.py (bridge, default thinking, --require-model-match on, global).
Stops launching at $50 proxy cost (sum of live ledger totals) or on any off_protocol cell."""
import json, os, random, subprocess, sys, threading, time, hashlib, glob
from concurrent.futures import ThreadPoolExecutor
REPO = os.path.expanduser("~/ob-pvo"); OUT = os.path.expanduser("~/pvo180")
TASKS = ["dna-insert","filter-js-from-html","model-extraction-relu-logits","polyglot-rust-c","regex-chess",
         "sam-cell-seg","torch-pipeline-parallelism","torch-tensor-parallelism","video-processing"]
CAP = float(os.environ.get("PVO_CAP", "50")); JOBS = int(os.environ.get("PVO_JOBS", "3"))
cells = [(h, t, r) for h in ("pi", "opencode") for t in TASKS for r in range(1, 11)]
random.Random(20261024).shuffle(cells)
assert len(cells) == 180
os.makedirs(OUT, exist_ok=True)
order = "\n".join(f"{i},{h},{t},{r}" for i, (h, t, r) in enumerate(cells)) + "\n"
open(f"{OUT}/order.csv", "w").write("idx,harness,task,run\n" + order)
open(f"{OUT}/order.sha256", "w").write(hashlib.sha256(order.encode()).hexdigest() + "\n")
sys.path.insert(0, REPO)
from thesis.ab.summarize import row_cost
stop = threading.Event(); reason = []
def spend():
    tot = 0.0
    for f in glob.glob(f"{OUT}/cells/*/*/proxy-ledger/*.totals.json"):
        try: a = json.load(open(f))["all"]
        except Exception: continue
        tot += row_cost({"upstream_model": "claude-sonnet-5-5", "tokens_input_uncached": a["input_uncached"],
            "tokens_output": a["output"], "tokens_cache_read": a["cache_read"], "tokens_cache_write": a["cache_write"]}) or 0
    return tot
def log(s):
    line = time.strftime("%Y-%m-%d %H:%M:%S %Z ") + s
    print(line, flush=True); open(f"{OUT}/batch.log", "a").write(line + "\n")
procs = set()
def run(i):
    h, t, r = cells[i]
    if stop.is_set(): return
    d = f"{OUT}/cells/{i:03d}-{h}-{t}-r{r}"; os.makedirs(d, exist_ok=True)
    env = dict(os.environ)
    if h == "pi":
        code = ("import importlib.util,sys;s=importlib.util.spec_from_file_location('c','data/pi-harness-smoke/cell.py');"
                f"m=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.TASK={t!r};sys.exit(m.main(sys.argv[1:]))")
        cmd = ["python3", "-c", code, "--out", f"{d}/pi", "--models", "claude-sonnet-5-5", "--exec", "docker",
               "--image", "h1-env:1027-strace", "--cache", os.path.expanduser("~/h1/pi-src"), "--require-model-match"]
    else:
        cmd = ["python3", "data/opencode-harness-smoke/cell.py", "--out", f"{d}/opencode", "--task", t, "--exec", "docker",
               "--image", "h1-env:1027-strace", "--cache", os.path.expanduser("~/h1/opencode-src"),
               "--sha", env["OPENCODE_SHA"], "--node", env["OPENCODE_NODE_PREFIX"], "--vertex-model", "claude-sonnet-5-5",
               "--require-model-match"]
    log(f"start {i} {h} {t} r{r}")
    with open(f"{d}/cell.out", "w") as fh:
        p = subprocess.Popen(["timeout", "3000"] + cmd, cwd=REPO, env=env, stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)
        procs.add(p); rc = p.wait(); procs.discard(p)
    off = None
    for s in glob.glob(f"{d}/*/summary.json"):
        try: off = any(c.get("off_protocol") for c in json.load(open(s))["cells"])
        except Exception: pass
    log(f"end {i} {h} {t} r{r} rc={rc} off_protocol={off} spend=${spend():.2f}")
    if off:
        reason.append(f"off_protocol cell {i}"); stop.set()
def guard():
    while not stop.is_set():
        s = spend()
        if s >= CAP:
            reason.append(f"spend ${s:.2f} >= ${CAP}"); stop.set()
            for p in list(procs):
                try: os.killpg(p.pid, 15)
                except Exception: pass
        time.sleep(15)
threading.Thread(target=guard, daemon=True).start()
log(f"launch 180 cells jobs={JOBS} cap=${CAP} order_sha256={open(f'{OUT}/order.sha256').read().strip()}")
with ThreadPoolExecutor(JOBS) as ex: list(ex.map(run, range(180)))
stopped = "; ".join(reason) or "none"; stop.set()
log(f"BATCH DONE stopped={stopped} spend=${spend():.2f}")
