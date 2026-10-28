#!/usr/bin/env python3
"""Step-8 scored-cell fault audit over FULL opencode logs (read-only).

For every cell transcript dir (<run>/<pr>/transcripts/<side>/<task>/<trial>/)
in the runs below, reads agent-output.txt (opencode --print-logs stdout+stderr)
and log/*.log as bytes (binary-safe), and records:
  - provider-fault signature lines (SIG), excluding bad-key auth errors;
  - recovered AI_TypeValidationError lines (counted separately);
  - the @ai-sdk/anthropic install line(s) opencode itself ran at getSDK
    ("installed @ai-sdk/anthropic@X"), and any "Unsupported model version vN".
Outcome comes from the run's <side>.jsonl row matched on (task, trial).
Writes results/step8-pins-D4/scored_fault_audit.csv (one row per cell).
"""
import csv, glob, json, os, re, sys
from collections import Counter
RUNS = ["step8-full413-1020-F01", "step8-full413-1020-F02", "step8-full413-1020-F02-rerun",
        "step8-full413-1020-F03", "step8-full413-1020-F03-1-rerun",
        "step8-sonnet447-pilot-1020-full", "step8-vm-F03-1-pinned-1026"]
SIG = re.compile(rb"Unhandled chunk type|Unsupported model version|stream error|AI_APICallError|overloaded_error|\"type\":\"api_error\"|api_error|AI_\w*Error|ProviderInitError|InitError|UnknownError")
TVE = re.compile(rb"AI_TypeValidationError")
AUTH = re.compile(rb"authentication_error|invalid x-api-key")
INSTALLED = re.compile(rb"installed @ai-sdk/anthropic@(\S+)")
INSTALLING = re.compile(rb"pkg=@ai-sdk/anthropic version=(\S+) installing")
SPEC = re.compile(rb"Unsupported model version (v\d+)")
GETSDK = re.compile(rb"status=completed duration=\d+ providerID=anthropic getSDK")

def outcomes(run):
    out = {}
    for f in glob.glob(f"results/{run}/**/*.jsonl", recursive=True):
        if "/transcripts/" in f or "proxy-ledger" in f or "/setaside/" in f: continue
        side = os.path.basename(f).split(".")[0]
        pr = os.path.basename(os.path.dirname(f))
        for l in open(f, errors="replace"):
            try: d = json.loads(l)
            except ValueError: continue
            if "cell_seed" in d:
                out[(pr, side, d.get("task"), str(d.get("trial")))] = d.get("failure_class") or ("solved" if d.get("success") else "")
    return out

rows = []
for run in RUNS:
    oc = outcomes(run)
    for cell in sorted(glob.glob(f"results/{run}/**/transcripts/*/*/*/", recursive=True)):
        if "/setaside/" in cell or "/storage/" in cell: continue
        parts = cell.rstrip("/").split("/")
        pr, side, task, trial = parts[-5], parts[-3], parts[-2], parts[-1]
        files = [cell + "agent-output.txt"] + glob.glob(cell + "log/*.log")
        sig, tve, inst, insting, spec, getsdk = [], 0, set(), set(), set(), 0
        for fp in files:
            if not os.path.exists(fp): continue
            for i, ln in enumerate(open(fp, "rb").read().splitlines(), 1):
                if TVE.search(ln): tve += 1; continue
                if SIG.search(ln) and not AUTH.search(ln):
                    sig.append(f"{os.path.relpath(fp, cell)}:{i}: " + ln[:220].decode("utf-8", "replace"))
                m = INSTALLED.search(ln);  m and inst.add(m.group(1).decode())
                m = INSTALLING.search(ln); m and insting.add(m.group(1).decode())
                m = SPEC.search(ln);       m and spec.add(m.group(1).decode())
                if GETSDK.search(ln): getsdk += 1
        rows.append(dict(run=run, pr=pr, side=side, task=task, trial=trial,
                         outcome=oc.get((pr, side, task, trial), "no_row"),
                         has_log="yes" if any(os.path.exists(f) for f in files) else "no",
                         sig_hits=len(sig), tve_lines=tve,
                         opencode_installed="|".join(sorted(inst)), opencode_installing="|".join(sorted(insting)),
                         spec_error="|".join(sorted(spec)), getsdk_completed=getsdk,
                         first_sig_line=sig[0] if sig else ""))
os.makedirs("results/step8-pins-D4", exist_ok=True)
with open("results/step8-pins-D4/scored_fault_audit.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n"); w.writeheader(); w.writerows(rows)
c = Counter((r["run"], r["sig_hits"] > 0) for r in rows)
for run in RUNS:
    rr = [r for r in rows if r["run"] == run]
    print(run, "cells", len(rr), "no_row", sum(r["outcome"] == "no_row" for r in rr), "nolog", sum(r["has_log"] == "no" for r in rr),
          "hit_cells", sum(r["sig_hits"] > 0 for r in rr), "tve_cells", sum(r["tve_lines"] > 0 for r in rr),
          "installed", Counter(r["opencode_installed"] or "-" for r in rr), "spec", Counter(r["spec_error"] or "-" for r in rr))
