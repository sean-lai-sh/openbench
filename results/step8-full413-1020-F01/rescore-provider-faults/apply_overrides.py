#!/usr/bin/env python3
"""Reproducible F01 provider-fault rescore (Researcher ruling 2026-10-26).
Reads overrides.csv, builds an overlay copy of each affected PR under
<out>/<pr>/cells (originals never touched), and applies:
  scoring=exclude    -> failure_class := to_class (infra: out of pass rate and tokens)
  scoring=label_only -> failure_class unchanged for scoring; adds
                        failure_class_relabel := to_class + relabel_evidence
Then runs the frozen step-8 metrics (results/step8-full413-1020/stats.py)
on before (originals) and after (overlay).
usage: PYTHONPATH=<repo> python3 apply_overrides.py <repo_root> <out_dir>"""
import csv, json, os, shutil, subprocess, sys
root, out = sys.argv[1], sys.argv[2]
here = os.path.dirname(os.path.abspath(__file__))
ov = list(csv.DictReader(open(os.path.join(here, "overrides.csv"))))
stats = os.path.join(root, "results/step8-full413-1020/stats.py")
env = dict(os.environ, PYTHONPATH=root)
for d in ("before", "after"):
    shutil.rmtree(os.path.join(out, d), ignore_errors=True)
for o in ov:
    src = os.path.join(root, "results", o["run"], o["pr"])
    os.makedirs(os.path.join(out, "before"), exist_ok=True)
    b = os.path.join(out, "before", o["pr"])
    if not os.path.exists(b): os.symlink(src, b)
    a = os.path.join(out, "after", o["pr"], "cells")
    if not os.path.exists(a): shutil.copytree(os.path.join(src, "cells"), a)
    f = os.path.join(a, o["side"], o["task"], o["trial"] + ".json")
    r = json.load(open(f))
    assert r.get("failure_class") == o["from_class"], (f, r.get("failure_class"))
    if o["scoring"] == "exclude":
        r["failure_class_orig"] = r["failure_class"]; r["failure_class"] = o["to_class"]
        r["success"] = False; r["infra_reason"] = "provider_fault_rescore"
    else:
        r["failure_class_relabel"] = o["to_class"]
    r["relabel_evidence"] = o["evidence"]
    json.dump(r, open(f, "w"), sort_keys=True)
for d in ("before", "after"):
    res = subprocess.run([sys.executable, stats, os.path.join(out, d)], env=env, capture_output=True, text=True, check=True)
    open(os.path.join(here, f"stats-{d}.txt"), "w").write(res.stdout)
    print(f"== {d}\n{res.stdout}")
