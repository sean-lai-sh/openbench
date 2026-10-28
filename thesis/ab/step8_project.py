"""F03-2 spend projection (launcher helper).

Cumulative projection = spent so far (prior + every cell in the run dir) +
for each side still short of ``n`` scored cells: remaining cells x that
side's gate-cell cost x max(pooled ratio, the PR's own ratio if it has one).

Pooled ratio = scored cost / gate-equivalent cost, over PRs whose sides are
all finished (n scored cells each). Before any PR finishes it falls back to
``FALLBACK_RATIO`` (1.0: a scored cell costs what its gate cell did).
Replaces the flat average over all cells, which mispriced the whole batch
from the first (most expensive) PR's cells.

``spent`` is every cell. Completion and the ratio use the same cells as
``step8_gate.complete()``: on-route and scorable, with a tagged rerun
replacing its off-route original. Off-route cost stays in ``spent`` and does
not count toward ``n``.

``--phase-cap`` prints the ``--max-cost-usd`` for one phase directory:
stop minus prior minus cell spend outside that directory. ``run_ab.over_budget``
sums cells already in the directory, so subtracting them here would count
them twice when a run resumes.

``python -m thesis.ab.step8_project <run_dir> [--prior X] [--stop Y] [--n 30]``
prints JSON; exit 1 when the projection exceeds the stop.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

from thesis.ab.step8_gate import assemble_cells, on_route_scored, pair_route_split, route_ok

FALLBACK_RATIO = 1.0


def _cost(c: dict) -> float:
    return float(c.get("requests_cost_usd") or 0)


def _cell_paths(run_dir: str):
    return glob.glob(os.path.join(run_dir, "[gsr]*", "*", "cells", "*", "*", "*.json"))


def phase_cap(run_dir: str, phase: str, stop: float, prior: float = 0.0) -> float:
    """``--max-cost-usd`` for one phase directory.

    Cells already in ``phase`` are counted by ``run_ab.over_budget``. The cap
    subtracts only prior spend and cells outside that directory, so each cell
    counts once when a scored or rerun phase resumes.
    """
    outside = 0.0
    for f in _cell_paths(run_dir):
        if os.path.relpath(f, run_dir).split(os.sep)[0] == phase:
            continue
        with open(f) as fh:
            outside += _cost(json.load(fh))
    return round(stop - prior - outside, 2)


def load(run_dir: str) -> tuple[dict, dict, float, frozenset]:
    """(gate cost per pr/side, eligible scored costs, all cell spend, blocked PRs).

    Eligible costs are the cells ``step8_gate.complete()`` counts. Blocked PRs
    are the ones ``complete()`` will not finish (split route or a mismatched side).
    """
    with open(os.path.join(run_dir, "gate.json")) as fh:
        g = json.load(fh)
    ok = {str(p) for p in (g.get("ok_prs") or [])}
    gate = {}
    for c in g["cells"]:
        if str(c.get("pr")) in ok:
            gate[(str(c["pr"]), c["side"])] = float(c.get("cost") or 0)
    spent = 0.0
    for f in _cell_paths(run_dir):
        with open(f) as fh:
            spent += _cost(json.load(fh))
    reruns = [os.path.join(run_dir, "rerun")] if os.path.isdir(os.path.join(run_dir, "rerun")) else []
    cells, _untagged = assemble_cells(os.path.join(run_dir, "scored"), reruns)
    scored = {}
    for (pr, side), rows in on_route_scored(cells).items():
        scored[(pr, side)] = [_cost(c) for _f, c in rows]
    split = pair_route_split([
        dict(pr=k[0], route=c.get("route")) for k, (_f, c) in cells.items() if route_ok(c)])
    blocked = set(split)
    for key in g.get("mismatch_sides") or []:
        blocked.add(str(key).split("/")[0])
    return gate, scored, spent, frozenset(blocked)


def project(gate: dict, scored: dict, spent: float, prior: float = 0.0, n: int = 30,
            blocked=()) -> dict:
    prs = sorted({pr for pr, _ in gate})

    def sides(pr):
        return [k for k in gate if k[0] == pr]

    def ratio(keys):
        num = sum(sum(scored.get(k, [])) for k in keys)
        den = sum(gate[k] * len(scored.get(k, [])) for k in keys)
        return num / den if den > 0 else None

    blocked = {str(p) for p in blocked}
    done = [pr for pr in prs if pr not in blocked and all(len(scored.get(k, [])) >= n for k in sides(pr))]
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
    ap.add_argument("--phase-cap", choices=("gate", "scored", "rerun"), default=None)
    a = ap.parse_args(argv)
    if a.phase_cap:
        print(phase_cap(a.run_dir, a.phase_cap, a.stop, a.prior))
        return 0
    gate, scored, spent, blocked = load(a.run_dir)
    out = project(gate, scored, spent, prior=a.prior, n=a.n, blocked=blocked)
    out["stop"] = a.stop
    print(json.dumps(out, sort_keys=True))
    return 1 if out["projected"] > a.stop else 0


if __name__ == "__main__":
    sys.exit(main())
