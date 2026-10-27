"""F03-2 gate-cell check: did each side load its pinned provider?

Reads the traced gate cells (one per side). ``probe_method`` says how the
version was read: ``strace`` (package opened from node_modules) or
``embedded`` (provider bundled into the binary, version read from the
bundle). Either counts as proof; a bundled side is not a mismatch merely
because strace saw nothing. A cell with no probe value is unproven.

Every cell also carries ``route`` (thesis.ab.route): ``on:<how>`` when its
requests reached the expected endpoint, ``off:<how>`` when none did. A
missing route fails closed. An off-route cell is infra: not scored, rerun.
More than 2 off-route cells on a side halts that side; more than 2 halted
sides halts the batch (same thresholds as provider mismatch).

Reruns: cells rerun from the ``rerun`` list are tagged ``rerun=1`` and go
through the same route check. ``--complete`` decides which sides are scored:
a side needs a passed gate and 30 on-route scored cells (originals plus
tagged reruns replacing off-route originals); otherwise it is reported
``incomplete`` and not padded.

Usage:
  python -m thesis.ab.step8_gate RUN_DIR PINS_JSON SIDES_JSON [--later]
  python -m thesis.ab.step8_gate --route RUN_DIR
  python -m thesis.ab.step8_gate --complete SCORED_DIR GATE_JSON [RERUN_DIR ...]
Exit 1 when more than 2 sides fail or fewer than 22 sides were seen
(``--route``: when more than 2 sides are halted).
"""
from __future__ import annotations

import glob
import json
import os
import sys
from datetime import datetime

PROBE_METHODS = ("strace", "embedded")
MAX_OFF_ROUTE_PER_SIDE = 2
MAX_BAD_SIDES = 2
SCORED_PER_SIDE = 30


def _load(path: str) -> dict:
    with open(path) as fh:
        return json.load(fh)


def _when(text) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None


def _spend_after_halt(run_dir: str, key: str, rows: list[tuple[str, dict]]) -> dict:
    """Spend on a halted side by cells that started at/after the halt.
    Halt time: run_ab's route-halt record, else the 3rd off-route cell's end."""
    pr, side = key.split("/")
    rec = os.path.join(run_dir, pr, f"route-halt-{side}.json")
    halted = _when(_load(rec).get("halted_at")) if os.path.isfile(rec) else None
    if halted is None:
        ends = sorted(t for t in (_when(c.get("ended_et")) for _, c in rows if not route_ok(c)) if t)
        halted = ends[MAX_OFF_ROUTE_PER_SIDE] if len(ends) > MAX_OFF_ROUTE_PER_SIDE else None
    after = [(f, c) for f, c in rows if halted is not None
             and (_when(c.get("started_et")) or datetime.min.replace(tzinfo=halted.tzinfo)) >= halted]
    return dict(halted_at=halted.isoformat() if halted else None, cells_after=len(after),
                spend_after_usd=round(sum(c.get("requests_cost_usd") or 0 for _, c in after), 4))


def route_ok(cell: dict) -> bool:
    return str(cell.get("route") or "").startswith("on:")


def _cell_files(run_dir: str):
    for f in sorted(glob.glob(f"{run_dir}/*/cells/*/*/*.json")):
        p = f.split("/")
        yield f, p[-5], p[-3]


def route_check(run_dir: str) -> tuple[dict, int]:
    """Off-route cells to rerun as infra, and sides/batch to halt."""
    off, total, rows = {}, {}, {}
    for f, pr, side in _cell_files(run_dir):
        key = f"{pr}/{side}"
        total[key] = total.get(key, 0) + 1
        c = _load(f)
        rows.setdefault(key, []).append((f, c))
        if not route_ok(c):
            off.setdefault(key, []).append(
                dict(cell=os.path.relpath(f, run_dir), route=c.get("route") or "off:missing"))
    halted = sorted(k for k, v in off.items() if len(v) > MAX_OFF_ROUTE_PER_SIDE)
    out = dict(cells=sum(total.values()), sides_seen=len(total),
               off_route=off, rerun=[x["cell"] for v in off.values() for x in v],
               label="infra:off_route", halted_sides=halted,
               halt_batch=len(halted) > MAX_BAD_SIDES,
               halted_spend={k: _spend_after_halt(run_dir, k, rows[k]) for k in halted})
    return out, (1 if out["halt_batch"] else 0)


def _cell_key(f: str) -> tuple[str, str, str, str]:
    p = f.split("/")
    return p[-5], p[-3], p[-2], p[-1]


def complete(scored_dir: str, gate: dict, rerun_dirs=()) -> tuple[dict, int]:
    """Sides to score: gate-passed PR and 30 on-route scored cells. A tagged
    rerun (``rerun=1``) replaces its off-route original; untagged cells in a
    rerun dir are ignored. Never padded: a short side is ``incomplete``."""
    cells = {}
    for f, _pr, _side in _cell_files(scored_dir):
        cells[_cell_key(f)] = (f, _load(f))
    untagged = []
    for d in rerun_dirs:
        for f, _pr, _side in _cell_files(d):
            c = _load(f)
            if c.get("rerun") != 1:
                untagged.append(f)
                continue
            k = _cell_key(f)
            if k not in cells or not route_ok(cells[k][1]):
                cells[k] = (f, c)
    split = pair_route_split([dict(pr=k[0], route=c.get("route")) for k, (f, c) in cells.items()
                              if route_ok(c)])
    ok_prs = set(gate.get("ok_prs") or [])
    bad = set(gate.get("mismatch_sides") or [])
    sides = {}
    for k, (f, c) in sorted(cells.items()):
        sides.setdefault(f"{k[0]}/{k[1]}", []).append((f, c))
    out = dict(complete={}, incomplete={}, untagged_rerun_cells=untagged)
    for key, rs in sorted(sides.items()):
        on = [f for f, c in rs if route_ok(c)]
        why = None
        if key.split("/")[0] not in ok_prs or key in bad:
            why = "gate not passed"
        elif key.split("/")[0] in split:
            why = split[key.split("/")[0]]
        elif len(on) < SCORED_PER_SIDE:
            why = f"{len(on)}/{SCORED_PER_SIDE} on-route scored cells"
        if why:
            out["incomplete"][key] = dict(on_route=len(on), cells=len(rs), why=why)
        else:
            out["complete"][key] = dict(on_route=len(on), cells=sorted(on)[:SCORED_PER_SIDE],
                                        reruns=sum(1 for f, c in rs if c.get("rerun") == 1 and route_ok(c)))
    return out, 0


def pin_for(pins: dict, sha: str, side: str) -> str:
    return str((((pins.get(sha) or {}).get(side) or {}).get("packages") or {}).get("@ai-sdk/anthropic") or "")


def judge(cell: dict, pin: str) -> tuple[bool, str]:
    """(ok, why) for one gate cell against its pin."""
    method = cell.get("probe_method") or ""
    loaded = str(cell.get("provider_loaded_version") or "")
    if method not in PROBE_METHODS or not loaded:
        return False, "loaded version unproven"
    if cell.get("provider_loaded_mismatch"):
        return False, str(cell["provider_loaded_mismatch"])
    if not pin:
        return False, f"no pin ({method} saw {loaded})"
    if loaded != pin:
        return False, f"{method} loaded {loaded} != pin {pin}"
    return True, f"{method} {loaded}"


def _how(route) -> str:
    return str(route or "").partition(":")[2]


def pair_route_split(rows) -> dict:
    """{pr: why} for pairs whose cells did not all take one route (both sides,
    every cell). Rows need ``pr`` and ``route``."""
    hows = {}
    for x in rows:
        hows.setdefault(x["pr"], set()).add(_how(x.get("route")))
    return {pr: "pair route differs: " + ",".join(sorted(h)) for pr, h in hows.items() if len(h) > 1}


def evaluate(run_dir: str, pins: dict, sides: dict, later: bool = False) -> tuple[dict, int]:
    cells, bad = [], {}
    for f, pr, side in _cell_files(run_dir):
        c = _load(f)
        sha = sides[pr][side]
        pin = pin_for(pins, sha, side)
        ok, why = judge(c, pin)
        if ok and not route_ok(c):
            ok, why = False, f"route {c.get('route') or 'off:missing'}"
        rel = os.path.relpath(f, run_dir)
        cells.append(dict(cell=rel, pr=pr, side=side, sha=sha, pin=pin,
                          loaded=c.get("provider_loaded_version"),
                          probe_method=c.get("probe_method") or "",
                          loaded_source=c.get("provider_loaded_source"),
                          mismatch_field=c.get("provider_loaded_mismatch"),
                          route=c.get("route") or "",
                          ok=ok, why=why, cost=c.get("requests_cost_usd")))
        if not ok:
            bad.setdefault(f"{pr}/{side}", []).append(rel)
    for pr, why in pair_route_split([x for x in cells if route_ok(x)]).items():
        for x in cells:
            if x["pr"] == pr and x["ok"]:
                x["ok"], x["why"] = False, why
                bad.setdefault(f"{pr}/{x['side']}", []).append(x["cell"])
    if later:
        return dict(cells=cells, rerun=[x for v in bad.values() for x in v],
                    label="infra:provider_pin_mismatch_or_off_route"), 0
    seen = {f"{x['pr']}/{x['side']}" for x in cells}
    badpr = {k.split("/")[0] for k in bad}
    out = dict(cells=cells, first_cells=len(cells), sides_seen=len(seen),
               mismatch_sides=sorted(bad), infra_cells=bad,
               ok_prs=sorted({x["pr"] for x in cells} - badpr),
               cost=round(sum(x["cost"] or 0 for x in cells), 2))
    return out, (1 if len(bad) > MAX_BAD_SIDES or len(seen) < 22 else 0)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--complete"]:
        out, rc = complete(argv[1], _load(argv[2]), argv[3:])
        json.dump(out, sys.stdout, indent=1)
        return rc
    if argv[:1] == ["--route"]:
        out, rc = route_check(argv[1])
        json.dump(out, sys.stdout, indent=1)
        return rc
    later = "--later" in argv
    argv = [a for a in argv if a != "--later"]
    run_dir, pins_path, sides_path = argv[:3]
    out, rc = evaluate(run_dir, json.load(open(pins_path))["builds"], json.load(open(sides_path)), later)
    json.dump(out, sys.stdout, indent=1)
    return rc


if __name__ == "__main__":
    sys.exit(main())
