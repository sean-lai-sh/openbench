#!/usr/bin/env python3
"""[batch2: replaces m245g-batch.py from cell 3 on. Stops a cell gracefully (docker kill the agent container first, then wait up to 240 s
for cell.py to write its record) and allows 40 calls; cells 1-2 of batch 1 were SIGTERMed and wrote no cell record, so they are re-run as 5-6.]
PR #245 gating smoke at 77644112: {Pi, OpenCode} x {Sonnet 5.5, Opus 5.5} x regex-chess x 1 trial, --matched-config
(Opus also --matched-effort low). Not scored.
Body capture (in the cell process; no repo file changed), per proxy request NNNN:
  NNNN.received.bin  exact bytes read from the client socket (captured at the proxy's own json.loads of rfile bytes in do_POST)
  NNNN.edited.json   body handed to translate_body (after strip/sampling/block-binding/thinking edits)
  NNNN.upstream.json exact bytes translate_body returns, i.e. the body POSTed to Vertex
  NNNN.meta.json     route, cell, time, sha256s
Guards: total $4.00, per cell $0.55 (live ledger rows), 20 calls or 1800 s wall per cell."""
import json, os, subprocess, sys, threading, time, glob
REPO = os.path.expanduser("~/ob-m245g"); OUT = os.path.expanduser("~/h2/matched245-gate-1112")
TASK = "regex-chess"; CAP = 4.00; CELL_CAP = 0.55; MAX_CALLS = 40; MAX_WALL = 1800
sys.path.insert(0, REPO)
from thesis.ab.summarize import row_cost
stop = threading.Event()
def ledger_rows(d):
    rows = []
    for f in glob.glob(f"{d}/*/proxy-ledger/*.jsonl"):
        if not os.path.basename(f)[:-6].isalnum(): continue
        for l in open(f):
            try: rows.append(json.loads(l))
            except Exception: pass
    return rows
def cost(rows, m):
    return sum(row_cost({"upstream_model": r.get("upstream_model") or m, "tokens_input_uncached": r.get("input_uncached") or 0,
                         "tokens_output": r.get("output") or 0, "tokens_cache_read": r.get("cache_read") or 0,
                         "tokens_cache_write": r.get("cache_write") or 0}) or 0 for r in rows)
def spend():
    return sum(cost(ledger_rows(d), "claude-opus-5-5" if "opus" in d else "claude-sonnet-5-5") for d in glob.glob(f"{OUT}/cells/*"))
def log(s):
    line = time.strftime("%Y-%m-%d %H:%M:%S %Z ") + s
    print(line, flush=True); open(f"{OUT}/batch.log", "a").write(line + "\n")
def kill_my_containers(d):
    for c in subprocess.run(["docker", "ps", "-q"], capture_output=True, text=True).stdout.split():
        mnt = subprocess.run(["docker", "inspect", "-f", "{{range .Mounts}}{{.Source}} {{end}}", c], capture_output=True, text=True).stdout
        if d in mnt or f"{REPO}/" in mnt:
            subprocess.run(["docker", "kill", c], capture_output=True); log(f"docker kill {c}")
CAPTURE = r'''
import importlib.util, sys, os, json as _json, threading, hashlib, time
import thesis.ab.vertex_anthropic_proxy as v
_d = os.path.join(sys.argv[sys.argv.index("--out") + 1], "requests"); os.makedirs(_d, exist_ok=True)
_n = [0]; _l = threading.Lock(); _tl = threading.local()
class _J:
    def __getattr__(self, a): return getattr(_json, a)
    def loads(self, s, *a, **k):
        if getattr(_tl, "armed", False) and sys._getframe(1).f_code.co_name == "do_POST":
            _tl.armed = False
            raw = s.encode("utf-8") if isinstance(s, str) else bytes(s)
            with _l:
                _n[0] += 1; _tl.k = _n[0]
            open(os.path.join(_d, "%%04d.received.bin" %% _tl.k), "wb").write(raw)
            _tl.meta = {"k": _tl.k, "route": getattr(_tl, "path", None), "t_received": time.time(),
                        "received_sha256": hashlib.sha256(raw).hexdigest(), "received_bytes": len(raw)}
        return _json.loads(s, *a, **k)
v.json = _J()
_split = v.split_cell_path
def _split_cell_path(path):
    if sys._getframe(1).f_code.co_name == "do_POST":
        _tl.armed = True; _tl.k = None; _tl.path = path
    return _split(path)
v.split_cell_path = _split_cell_path
_tb = v.translate_body
def _translate_body(path, body):
    kind, out = _tb(path, body)
    k = getattr(_tl, "k", None)
    if k is None:
        with _l:
            _n[0] += 1; k = _n[0]
        _tl.meta = {"k": k, "route": path, "received": "not captured"}
    open(os.path.join(_d, "%%04d.edited.json" %% k), "wb").write(body)
    open(os.path.join(_d, "%%04d.upstream.json" %% k), "wb").write(out)
    m = dict(getattr(_tl, "meta", {}) or {}); m.update({"translate_route": path, "kind": kind, "t_forward": time.time(),
        "edited_sha256": hashlib.sha256(body).hexdigest(), "upstream_sha256": hashlib.sha256(out).hexdigest(), "upstream_bytes": len(out)})
    open(os.path.join(_d, "%%04d.meta.json" %% k), "w").write(_json.dumps(m))
    _tl.k = None
    return kind, out
v.translate_body = _translate_body
H = %r; TASK = %r
if H == "pi":
    s = importlib.util.spec_from_file_location("c", "data/pi-harness-smoke/cell.py"); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); m.TASK = TASK
else:
    s = importlib.util.spec_from_file_location("c", "data/opencode-harness-smoke/cell.py"); m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
sys.exit(m.main(sys.argv[1:]))
'''
def run(i, h, m):
    d = f"{OUT}/cells/{i}-{h}-{m}-{TASK}" + ("-rerun" if i >= 5 else ""); os.makedirs(d, exist_ok=True)
    env = dict(os.environ); env["OBENCH_MATCHED_CONFIG"] = "1"
    eff = ["--matched-effort", "low"] if "opus" in m else []
    if h == "pi":
        args = ["--out", f"{d}/pi", "--models", m, "--exec", "docker", "--image", "h1-env:1027-strace",
                "--cache", os.path.expanduser("~/h1/pi-src"), "--require-model-match", "--matched-config"] + eff
    else:
        args = ["--out", f"{d}/opencode", "--task", TASK, "--exec", "docker", "--image", "h1-env:1027-strace",
                "--cache", os.path.expanduser("~/h1/opencode-src"), "--sha", env["OPENCODE_SHA"], "--node", env["OPENCODE_NODE_PREFIX"],
                "--model", m, "--require-model-match", "--matched-config"] + eff
    cmd = ["python3", "-c", CAPTURE % (h, TASK)] + args
    open(f"{d}/cmd.json", "w").write(json.dumps(cmd, indent=1) + "\n")
    t0 = time.time(); log(f"start {i} {h} {m} {TASK} {args[-3:] if eff else args[-2:]}")
    fh = open(f"{d}/cell.out", "w")
    p = subprocess.Popen(["timeout", "3600"] + cmd, cwd=REPO, env=env, stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)
    return watch(i, h, m, d, p.pid, t0, p)
def alive(pid, p):
    if p is not None: return p.poll() is None
    try: os.kill(pid, 0); return True
    except OSError: return False
def watch(i, h, m, d, pid, t0, p=None):
    why = None
    while alive(pid, p):
        rows = ledger_rows(d)
        if len(rows) >= MAX_CALLS: why = f"calls>={MAX_CALLS}"
        elif time.time() - t0 > MAX_WALL: why = f"wall>{MAX_WALL}s"
        elif cost(rows, m) >= CELL_CAP: why = f"cell spend>={CELL_CAP}"
        elif spend() >= CAP: why = f"spend>={CAP}"; stop.set()
        if why:
            log(f"stopping cell {i}: {why} (graceful: kill agent container, wait for cell record)")
            kill_my_containers(d)
            for _ in range(48):
                if not alive(pid, p): break
                time.sleep(5)
            if alive(pid, p):
                log(f"cell {i} still running 240 s after container kill; SIGTERM")
                try: os.killpg(pid, 15)
                except Exception: pass
            break
        time.sleep(5)
    rc = p.wait() if p is not None else "adopted"
    rec = glob.glob(f"{d}/{h}/claude-*.json")
    log(f"end {i} {h} {m} rc={rc} stopped={why or 'no'} record={'yes' if rec else 'no'} calls={len(ledger_rows(d))} wall_s={time.time()-t0:.0f} cell=${cost(ledger_rows(d), m):.3f} spend=${spend():.3f}")
log(f"batch2 launch: adopt cell 3 (pid {sys.argv[1]}), then 4 opencode opus, 5 pi sonnet (re-run of 1), 6 opencode sonnet (re-run of 2); cap=${CAP} cell_cap=${CELL_CAP} calls={MAX_CALLS} wall={MAX_WALL}s")
watch(3, "pi", "claude-opus-5-5", f"{OUT}/cells/3-pi-claude-opus-5-5-{TASK}", int(sys.argv[1]), float(sys.argv[2]))
for i, h, m in ((4, "opencode", "claude-opus-5-5"), (5, "pi", "claude-sonnet-5-5"), (6, "opencode", "claude-sonnet-5-5")):
    if stop.is_set(): break
    run(i, h, m)
log(f"BATCH2 DONE spend=${spend():.3f}")
