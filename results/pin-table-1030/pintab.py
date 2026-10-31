import json, csv, glob, os, subprocess, collections, sys, tempfile
from pathlib import Path
from datetime import datetime, timezone
sys.path.insert(0, os.path.expanduser("~/wt-sdkpin"))
from thesis.ab import sdk_pin
M = os.path.expanduser("~/h1/opencode-src/mirror")
def git(*a):
    r = subprocess.run(["git", "-C", M, *a], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None

# npm time / registry
anth = json.load(open("/tmp/anth.json"))
times = anth.get("time") or anth
rel = sorted(((datetime.fromisoformat(t.replace("Z", "+00:00")), v) for v, t in times.items()
              if v not in ("created", "modified")), key=lambda x: x[0])
PUB = {v: t.isoformat() for t, v in rel}
registry = {v: (i.get("dependencies") or {}).get("@ai-sdk/provider") for v, i in (anth.get("versions") or {}).items()} or None
def latest_at(ts, provider=None, stable=True):
    best = None
    for t, v in rel:
        if stable and "-" in v: continue
        if provider and registry.get(v) != provider: continue
        if t <= ts and (best is None or sdk_pin.version_sort_key(v) > sdk_pin.version_sort_key(best)):
            best = v
    return best

# builds from CSVs
builds = {}  # (pr) -> {side: sha}
for r in csv.DictReader(open(os.path.expanduser("~/h2/h2prs.csv"))):
    builds[r["PR"]] = {"with": r["Merge commit SHA"], "without": r["Parent/base SHA"]}
for r in csv.DictReader(open(os.path.expanduser("~/h1/h1prs.csv"))):
    builds[r["PR"]] = {"aa-1": r["Merge commit SHA"], "aa-2": r["Merge commit SHA"]}

RUNS = [("H1", "h1-hardprobe-1022", "~/h1/h1-hardprobe-1022"),
        ("H2", "h2-hardsuite-1022", "~/h2/h2-hardsuite-1022"),
        ("H2", "h2-deferred-1023", "~/h2/h2-deferred-1023"),
        ("H2", "h2-deferred-26821-1024", "~/h2/h2-deferred-26821-1024")]
ORDER = {"h2-hardsuite-1022/deferred-opus-attempt1": 1, "h2-hardsuite-1022": 0, "h2-deferred-1023": 2, "h2-deferred-26821-1024": 3}
groups = []
for study, run, base in RUNS:
    base = os.path.expanduser(base)
    for f in sorted(glob.glob(f"{base}/*/*/*.jsonl")):
        parts = f[len(base) + 1:].split("/")
        sub, pr, arm = parts[0], parts[1], parts[2][:-6]
        if pr == "proxy-ledger" or pr not in builds or arm not in builds[pr]:
            continue
        rows = [json.loads(l) for l in open(f) if l.strip()]
        model = "opus" if "opus" in sub else "sonnet"
        runkey = f"{run}/deferred-opus-attempt1" if sub == "deferred-opus-attempt1" else run
        groups.append(dict(study=study, run=runkey, sub=sub, model=model, pr=pr, arm=arm,
                           sha=builds[pr][arm], rows=rows))
# scored = latest run per (model, pr) in H2; H1 all
latest = {}
for g in groups:
    if g["study"] == "H2":
        k = (g["model"], g["pr"])
        latest[k] = max(latest.get(k, -1), ORDER[g["run"]])
for g in groups:
    g["scored"] = g["study"] == "H1" or ORDER[g["run"]] == latest[(g["model"], g["pr"])]

# rerun set (env-rerun-total.md)
FULL = {("h2-hardsuite-1022", "sonnet", "795"), ("h2-hardsuite-1022", "sonnet", "913"), ("h2-hardsuite-1022", "opus", "913"),
        ("h2-hardsuite-1022", "opus", "3052"), ("h2-hardsuite-1022", "sonnet", "3052"), ("h2-deferred-1023", "opus", "5140")}
CELLS = set()
for r in csv.DictReader(open("/tmp/checker-timeout-workspaces.csv")):
    CELLS.add((r["model"], r["pr"], r["side"], r["task"], int(r["trial"])))
DROP = {("opus", "13090", "without", "model-extraction-relu-logits", 2), ("opus", "13090", "without", "model-extraction-relu-logits", 6),
        ("opus", "26821", "with", "model-extraction-relu-logits", 6), ("opus", "26821", "with", "model-extraction-relu-logits", 1),
        ("opus", "4204", "without", "torch-tensor-parallelism", 9)}
CELLS |= {("opus", "4204", "without", "sam-cell-seg", 1), ("opus", "4204", "without", "sam-cell-seg", 4), ("opus", "26821", "without", "model-extraction-relu-logits", 1)}
CELLS -= DROP
def in_rerun(g, r):
    if (g["run"], g["model"], g["pr"]) in FULL:
        return True
    return g["scored"] and (g["model"], g["pr"], g["arm"], r.get("task"), int(r.get("trial") or 0)) in CELLS

# per build facts
binfo = {}
tmp = Path(tempfile.mkdtemp())
for sha in sorted({g["sha"] for g in groups}):
    date = (git("log", "-1", "--format=%cI", sha) or "").strip()
    prov = None
    for p in ("packages/opencode/src/provider/provider.ts",):
        prov = git("show", f"{sha}:{p}")
    runtime_latest = bool(prov and "BunProc.install" in prov and '"latest"' in prov)
    pkg = git("show", f"{sha}:packages/opencode/package.json") or "{}"
    try:
        deps = json.loads(pkg).get("dependencies", {})
    except Exception:
        deps = {}
    declared = deps.get("@ai-sdk/anthropic")
    lock = git("show", f"{sha}:bun.lock")
    d = tmp / sha; d.mkdir()
    if lock: (d / "bun.lock").write_text(lock)
    (d / "package.json").write_text(pkg)
    try:
        pin = sdk_pin.anthropic_pin_for_tree(d, registry=registry)
    except Exception as e:
        pin = f"err:{e}"
    locked_oc = None; ai_v = ai_prov = None
    if lock:
        try:
            L = sdk_pin.load_jsonc(lock); pk = L.get("packages", {})
            e = pk.get("opencode/@ai-sdk/anthropic") or (pk.get("@ai-sdk/anthropic") if declared else None)
            locked_oc = e[0].rsplit("@", 1)[-1] if e else None
            oa = pk.get("opencode/ai") or pk.get("ai")
            if oa:
                ai_v = oa[0].rsplit("@", 1)[-1]; ai_prov = (oa[2] or {}).get("dependencies", {}).get("@ai-sdk/provider") if len(oa) > 2 and isinstance(oa[2], dict) else None
        except Exception:
            pass
    ts = datetime.fromisoformat(date) if date else None
    tsu = ts.astimezone(timezone.utc) if ts else None
    lat_any = latest_at(tsu) if ts else None
    tag = "beta" if (prov and 'BunProc.install(pkg, "beta")' in prov) else "latest"
    if not date:
        policy, rule = None, "gap"
    elif declared:
        policy, rule = locked_oc, "lockfile"
    else:
        policy = latest_at(tsu, ai_prov, stable=True)
        rule = "latest_at_build"
        if policy is None:
            policy = latest_at(tsu, ai_prov, stable=False); rule = "latest_at_build(no compatible stable; newest compatible prerelease, install tag " + tag + ")"
    lat = lat_any
    binfo[sha] = dict(date=date, runtime_latest=runtime_latest, declared=declared, locked_opencode=locked_oc,
                      current_pin=pin, latest_at_build=lat, policy_pin=policy, pin_rule=rule, ai=ai_v, ai_provider=ai_prov,
                      pin_publish_ts=PUB.get(policy), install_tag=tag, found=bool(date))

def installed(r):
    tc = r.get("toolchain") if isinstance(r.get("toolchain"), dict) else {}
    pv = r.get("provider_versions") if isinstance(r.get("provider_versions"), dict) else {}
    return str(r.get("installed_anthropic") or tc.get("anthropic") or pv.get("@ai-sdk/anthropic") or "none")

out = []
for g in groups:
    b = binfo[g["sha"]]
    inst = collections.Counter(installed(r) for r in g["rows"])
    cost = sum(float(r.get("requests_cost_usd") or 0) for r in g["rows"])
    rr = [r for r in g["rows"] if in_rerun(g, r)]
    off = [r for r in g["rows"] if g["scored"] and not in_rerun(g, r) and installed(r) != b["policy_pin"]]
    out.append(dict(study=g["study"], run=g["run"], model=g["model"], pr=g["pr"], arm=g["arm"], build=g["sha"][:10],
                    build_date=b["date"], scored=g["scored"], rows=len(g["rows"]), cost_usd=round(cost, 2),
                    current_pin=b["current_pin"], runtime_latest=b["runtime_latest"], declared=b["declared"] or "",
                    locked_opencode=b["locked_opencode"] or "", latest_at_build=b["latest_at_build"],
                    ai=b["ai"], ai_provider=b["ai_provider"], install_tag=b["install_tag"],
                    policy_pin=b["policy_pin"], pin_rule=b["pin_rule"], pin_publish_ts=b["pin_publish_ts"],
                    pin_changes=b["policy_pin"] != b["current_pin"],
                    installed=";".join(f"{k}x{v}" for k, v in inst.most_common()),
                    rerun_cells=len(rr), rerun_cost=round(sum(float(r.get("requests_cost_usd") or 0) for r in rr), 2),
                    scored_rows_on_other_version=len(off)))
os.makedirs(os.path.expanduser("~/pintab"), exist_ok=True)
with open(os.path.expanduser("~/pintab/pin-table.csv"), "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
json.dump(binfo, open(os.path.expanduser("~/pintab/builds.json"), "w"), indent=1)
print("missing builds:", [s[:10] for s, b in binfo.items() if not b["found"]])
for o in out:
    print("\t".join(str(o[k]) for k in ("run", "model", "pr", "arm", "build", "build_date", "scored", "rows", "cost_usd", "current_pin", "runtime_latest", "declared", "locked_opencode", "policy_pin", "installed", "rerun_cells", "rerun_cost", "scored_rows_on_other_version", "ai", "pin_rule", "pin_publish_ts")))
