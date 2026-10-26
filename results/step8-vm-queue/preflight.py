#!/usr/bin/env python3
"""Step-8 queue worktree preflight (stdlib only, runs on the VM host).

  preflight.py check LABEL PRS   -> exit 0 if every worktree the batch needs is usable, 3 if not
  preflight.py needed [LABEL..]  -> print SHAs needed by every SUBS.txt batch without DONE-<label> (minus LABELs)

A worktree is usable for a side when ~/h1/opencode-src/worktrees/<sha> has package.json,
packages/opencode/src/provider/provider.ts, a resolvable bun version with an executable ~/h1/opencode-src/bun/<ver>/bun,
and ~/ob-s8/thesis/ab/provider_pins.json has a pin for that sha+side.
with = merge commit sha, without = parent/base sha (prs.csv), as in run_ab.
"""
import csv, json, os, sys
from pathlib import Path

H = Path.home(); B = H / "s8"; CACHE = H / "h1/opencode-src"; WT = CACHE / "worktrees"
PINS = H / "ob-s8/thesis/ab/provider_pins.json"

def sides(prs):
    rows = {r["PR"].strip(): r for r in csv.DictReader(open(B / "prs.csv"))}
    out = []
    for pr in prs:
        r = rows.get(pr)
        if r is None:
            out.append((pr, "?", "")); continue
        out.append((pr, "with", r["Merge commit SHA"].strip().lower()))
        out.append((pr, "without", r["Parent/base SHA"].strip().lower()))
    return out

def bun_version(root):
    p = root / ".bun-version"
    if p.is_file() and p.read_text().strip():
        return p.read_text().strip().lstrip("v")
    pkg = json.loads((root / "package.json").read_text())
    raw = pkg.get("packageManager") or ""
    if isinstance(raw, str) and raw.startswith("bun@"):
        return raw.split("@", 1)[1].split("+", 1)[0].strip()
    eng = pkg.get("engines") or {}
    if isinstance(eng, dict) and isinstance(eng.get("bun"), str) and eng["bun"].strip():
        return eng["bun"].strip().lstrip("v").split("+", 1)[0]
    return ""

def problems(sha, side, pins):
    if not sha:
        return ["PR not in prs.csv"]
    root = WT / sha; bad = []
    if not root.is_dir():
        return [f"missing worktree {root}"]
    if not (root / "package.json").is_file():
        bad.append(f"no package.json in {root}")
    # node_modules is not required: the pin install runs the cached bun into the
    # OpenCode package cache, and the F03-1-pinned worktrees had none (240/240 clean).
    if not (root / "packages/opencode/src/provider/provider.ts").is_file():
        bad.append(f"no packages/opencode/src/provider/provider.ts in {root}")
    try:
        v = bun_version(root)
    except Exception as e:
        v = ""; bad.append(f"bun version unreadable in {root}: {e}")
    if v:
        bun = CACHE / "bun" / v / "bun"
        # the container runs as root, so a root-owned 0744 binary is fine: check any x bit
        if not (bun.is_file() and bun.stat().st_size > 0 and bun.stat().st_mode & 0o111):
            bad.append(f"bun {v} missing or not executable at {bun}")
    elif not bad:
        bad.append(f"no bun version in {root}")
    if side not in (pins.get(sha) or {}):
        bad.append(f"no provider pin for {sha} side={side}")
    return bad

def main():
    pins = json.load(open(PINS)).get("builds", {})
    if sys.argv[1] == "needed":
        skip = set(sys.argv[2:]); need = set()
        for line in open(B / "SUBS.txt"):
            parts = line.split()
            if len(parts) < 2 or (B / f"DONE-{parts[0]}").exists() or parts[0] in skip:
                continue
            need |= {s for _, _, s in sides(parts[1].split(",")) if s}
        print("\n".join(sorted(need))); return 0
    lab, prs = sys.argv[2], sys.argv[3].split(",")
    missing = 0
    for pr, side, sha in sides(prs):
        bad = problems(sha, side, pins)
        print(f"{lab} {pr} {side:7} {sha or '-'} {'OK' if not bad else 'MISSING: ' + '; '.join(bad)}")
        missing += bool(bad)
    print(f"{lab} preflight: {missing} of {2*len(prs)} sides not ready")
    return 3 if missing else 0

if __name__ == "__main__":
    sys.exit(main())
