#!/usr/bin/env python3
"""Validate step-8 deviation D4: pins by nearest box build (validate only).

Brief: briefs/step8-amendment-M1-deviation-D4-nearest-build-pins-2026-10-26.md.

Nearest (recorded here, D4 rule 2): positions are indexes on the OpenCode
first-parent history of --tip (default origin/dev), oldest = 0, from
``git rev-list --first-parent --reverse``. A sha not on that line is placed at
its first first-parent commit that contains it (``git rev-list
--ancestry-path`` nearest descendant on the line). distance = |pos(a)-pos(b)|.
Ties go to the earlier (lower position) build, then to the lower sha.
A PR's pin is the nearest box build to its without (parent) side, applied to
both sides (D4 rule 1).

  validate --mirror DIR [--out-dir DIR] [--subs SUBS --prs prs.csv]
    (a) within-PR check, (b) leave-one-out check, both over box_cache sides;
    with --subs/--prs and both checks passing, also writes proposed.csv
    (never provider_pins.json). Exit 1 if a check fails.
"""
from __future__ import annotations
import argparse, csv, glob, json, subprocess, sys
from collections import Counter, defaultdict
from pathlib import Path

PACKAGE = "@ai-sdk/anthropic"
ROOT = Path(__file__).resolve().parents[2]
PINS = Path(__file__).with_name("provider_pins.json")
FAIL_CLASSES = {"infra", "provider_pin_mismatch"}


def git(mirror, *a):
    return subprocess.run(["git", "-C", str(mirror), *a], capture_output=True, text=True, check=True).stdout


class Line:
    def __init__(self, mirror, tip):
        self.mirror, self.tip = mirror, tip
        self.order = git(mirror, "rev-list", "--first-parent", "--reverse", tip).split()
        self.idx = {s: i for i, s in enumerate(self.order)}
        self.how = {}

    def pos(self, sha):
        sha = git(self.mirror, "rev-parse", sha + "^{commit}").strip()
        if sha in self.idx:
            self.how[sha] = "first_parent"
            return self.idx[sha]
        path = git(self.mirror, "rev-list", "--ancestry-path", "--first-parent", f"{sha}..{self.tip}").split()
        cands = [self.idx[s] for s in path if s in self.idx]
        if not cands:
            path = git(self.mirror, "rev-list", "--ancestry-path", f"{sha}..{self.tip}").split()
            cands = [self.idx[s] for s in path if s in self.idx]
        self.how[sha] = "merged_into_line" if cands else "not_on_line"
        return min(cands) if cands else None


def nearest(p, cands):
    """cands: list of (pos, sha, version). Returns best or None."""
    ok = [c for c in cands if c[0] is not None]
    if p is None or not ok:
        return None
    return min(ok, key=lambda c: (abs(c[0] - p), c[0], c[1]))


def box_sides():
    m = json.loads(PINS.read_text())["builds"]
    return [(sha, side, str(e.get("pr") or ""), e["packages"].get(PACKAGE, ""))
            for sha, ss in sorted(m.items()) for side, e in sorted(ss.items())
            if e.get("pin_source") == "box_cache"], m


def failed_versions():
    """version -> Counter(failure_class) over step-8 cells in infra/pin-mismatch classes."""
    out = defaultdict(Counter)
    for f in glob.glob(str(ROOT / "results/step8-*/**/*.jsonl"), recursive=True):
        if "/transcripts/" in f or "proxy-ledger" in f:
            continue
        for l in open(f):
            try:
                d = json.loads(l)
            except ValueError:
                continue
            if "cell_seed" not in d:
                continue
            fc = d.get("failure_class") or ""
            err = str(d.get("error") or "")
            if fc in FAIL_CLASSES or "provider_pin_mismatch" in err:
                pv = d.get("provider_versions") or {}
                v = pv.get(PACKAGE) if isinstance(pv, dict) else None
                v = v or (d.get("toolchain") or {}).get("anthropic") or "unknown"
                out[v]["provider_pin_mismatch" if "provider_pin_mismatch" in err else fc] += 1
    return out


def write_csv(path, rows):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["none"], lineterminator="\n")
        w.writeheader(); w.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["validate"])
    ap.add_argument("--mirror", required=True, type=Path)
    ap.add_argument("--tip", default="origin/dev")
    ap.add_argument("--out-dir", type=Path)
    ap.add_argument("--subs", type=Path); ap.add_argument("--prs", type=Path)
    ap.add_argument("--from-batch", default="F03-2")
    a = ap.parse_args(argv)
    line = Line(a.mirror, a.tip)
    sides, manifest = box_sides()
    pos = {s: line.pos(s) for s in {r[0] for r in sides}}
    builds = {}  # sha -> version (box_cache)
    for sha, side, pr, v in sides:
        builds.setdefault(sha, set()).add(v)
    # (a) within-PR
    by_pr = defaultdict(dict)
    for sha, side, pr, v in sides:
        by_pr[pr][side] = (sha, v)
    within = []
    for pr, ss in sorted(by_pr.items(), key=lambda x: int(x[0] or 0)):
        vs = {v for _, v in ss.values()}
        within.append({"pr": pr, "with_sha": ss.get("with", ("", ""))[0], "with": ss.get("with", ("", ""))[1],
                       "without_sha": ss.get("without", ("", ""))[0], "without": ss.get("without", ("", ""))[1],
                       "both_sides": "yes" if len(ss) == 2 else "no",
                       "same": "yes" if len(ss) == 2 and len(vs) == 1 else ("n/a" if len(ss) < 2 else "no")})
    pairs = [r for r in within if r["both_sides"] == "yes"]
    diff = [r for r in pairs if r["same"] == "no"]
    # (b) leave-one-out; two variants: exclude own sha only; exclude own PR's builds too
    fails = failed_versions()
    loo = []
    for sha, side, pr, v in sides:
        pr_shas = {s for s, _ in by_pr[pr].values()}
        row = {"sha": sha, "side": side, "pr": pr, "box_cache": v, "pos": pos[sha], "placement": line.how.get(sha, "")}
        for tag, excl in (("loo", {sha}), ("lpo", pr_shas)):
            cands = [(pos[s], s, sorted(vv)[0]) for s, vv in builds.items() if s not in excl and len(vv) == 1]
            n = nearest(pos[sha], cands)
            row[f"{tag}_pin_from"] = n[1] if n else ""
            row[f"{tag}_dist"] = abs(n[0] - pos[sha]) if n else ""
            row[f"{tag}_pred"] = n[2] if n else "none"
            row[f"{tag}_match"] = "yes" if n and n[2] == v else "no"
            row[f"{tag}_pred_has_failures"] = "|".join(f"{k}:{c}" for k, c in sorted(fails.get(n[2], {}).items())) if n else ""
        loo.append(row)
    res = {}
    for tag in ("loo", "lpo"):
        miss = [r for r in loo if r[f"{tag}_match"] != "yes"]
        bad = [r for r in miss if r[f"{tag}_pred_has_failures"]]
        rate = (len(loo) - len(miss)) / len(loo)
        res[tag] = (rate, miss, bad, rate >= 0.95 and not bad)
    ok_a = not diff
    ok_b = res["loo"][3]
    print(f"(a) within-PR: {len(pairs) - len(diff)} of {len(pairs)} box PRs same version; differ: {[r['pr'] for r in diff]}")
    for tag in ("loo", "lpo"):
        rate, miss, bad, ok = res[tag]
        print(f"(b:{tag}) {len(loo) - len(miss)}/{len(loo)} = {rate:.1%}; misses {len(miss)}, on failed versions {len(bad)}; {'PASS' if ok else 'FAIL'}")
    print("failed versions:", {k: dict(v) for k, v in fails.items()})
    if a.out_dir:
        a.out_dir.mkdir(parents=True, exist_ok=True)
        write_csv(a.out_dir / "within_pr.csv", within)
        write_csv(a.out_dir / "leave_one_out.csv", loo)
        write_csv(a.out_dir / "failed_versions.csv",
                  [{"version": k, "class": c, "cells": n} for k, v in sorted(fails.items()) for c, n in sorted(v.items())])
    passed = ok_a and ok_b
    if passed and a.subs and a.prs and a.out_dir:
        rows = {r["PR"].strip(): r for r in csv.DictReader(open(a.prs))}
        cands = [(pos[s], s, sorted(vv)[0]) for s, vv in builds.items() if len(vv) == 1]
        out, on = [], False
        for l in open(a.subs):
            p = l.split()
            if len(p) < 2: continue
            on = on or p[0] == a.from_batch
            if not on: continue
            for pr in p[1].split(","):
                r = rows[pr]; w = r["Merge commit SHA"].strip().lower(); wo = r["Parent/base SHA"].strip().lower()
                has = subprocess.run(["git", "-C", str(a.mirror), "cat-file", "-e", f"{wo}:packages/opencode"]).returncode == 0
                n = nearest(line.pos(wo), cands)
                for side, sha in (("with", w), ("without", wo)):
                    out.append({"batch": p[0], "pr": pr, "side": side, "sha": sha,
                                "pin_source": "nearest_box_build" if has else "not_run_D4_rule4",
                                "pin_from": n[1] if n and has else "", "distance": abs(n[0] - line.pos(wo)) if n and has else "",
                                PACKAGE: n[2] if n and has else ""})
        write_csv(a.out_dir / "proposed_pins.csv", out)
        print("proposed rows:", len(out))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
