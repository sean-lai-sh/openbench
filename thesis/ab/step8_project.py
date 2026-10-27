"""F03-2 spend projection (launcher helper).

Cumulative projection = spent so far (prior + every cell in the run dir) +
for each side still short of ``n`` scored cells: remaining cells x that
side's gate-cell cost x max(pooled ratio, the PR's own ratio if it has one).

Pooled ratio = scored cost / gate-equivalent cost, over PRs whose sides are
all finished (n scored cells each). Before any PR finishes it falls back to
``FALLBACK_RATIO`` (1.0: a scored cell costs what its gate cell did).
Replaces the flat average over all cells, which mispriced the whole batch
from the first (most expensive) PR's cells.

``python -m thesis.ab.step8_project <run_dir> [--prior X] [--stop Y] [--n 30]``
prints JSON; exit 1 when the projection exceeds the stop.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

FALLBACK_RATIO = 1.0


def _cost(c: dict) -> float:
    return float(c.get("requests_cost_usd") or 0)


def load(run_dir: str) -> tuple[dict, dict, float]:
    """(gate cost per pr/side, scored costs per pr/side, all cell spend)."""
    g = json.load(open(os.path.join(run_dir, "gate.json")))
    gate = {}
    for c in g["cells"]:
        if c.get("pr") in g.get("ok_prs", []):
            gate[(str(c["pr"]), c["side"])] = float(c.get("cost") or 0)
    scored, spent = {}, 0.0
    for f in glob.glob(os.path.join(run_dir, "[gsr]*", "*", "cells", "*", "*", "*.json")):
        c = json.load(open(f))
        spent += _cost(c)
        parts = os.path.relpath(f, run_dir).split(os.sep)
        if parts[0] == "scored":
            scored.setdefault((parts[1], parts[3]), []).append(_cost(c))
    return gate, scored, spent


def project(gate: dict, scored: dict, spent: float, prior: float = 0.0, n: int = 30) -> dict:
    prs = sorted({pr for pr, _ in gate})

    def sides(pr):
        return [k for k in gate if k[0] == pr]

    def ratio(keys):
        num = sum(sum(scored.get(k, [])) for k in keys)
        den = sum(gate[k] * len(scored.get(k, [])) for k in keys)
        return num / den if den > 0 else None

    done = [pr for pr in prs if all(len(scored.get(k, [])) >= n for k in sides(pr))]
    pooled = ratio([k for pr in done for k in sides(pr)])
    pooled_used = pooled if pooled is not None else FALLBACK_RATIO
    per_pr, remaining = {}, 0.0
    for pr in prs:
        if pr in done:
            continue
        own = ratio(sides(pr))
        r = max(pooled_used, own) if own is not None else pooled_used
        cost = sum(max(0, n - len(scored.get(k, []))) * gate[k] * r for k in sides(pr))
        per_pr[pr] = dict(own_ratio=own, ratio=r, remaining_usd=round(cost, 4))
        remaining += cost
    return dict(spent=round(prior + spent, 4), remaining=round(remaining, 4),
                projected=round(prior + spent + remaining, 4), pooled_ratio=pooled,
                pooled_ratio_used=pooled_used, done_prs=done, per_pr=per_pr)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--prior", type=float, default=0.0)
    ap.add_argument("--stop", type=float, default=60.0)
    ap.add_argument("--n", type=int, default=30)
    a = ap.parse_args(argv)
    out = project(*load(a.run_dir), prior=a.prior, n=a.n)
    out["stop"] = a.stop
    print(json.dumps(out, sort_keys=True))
    return 1 if out["projected"] > a.stop else 0


if __name__ == "__main__":
    sys.exit(main())
