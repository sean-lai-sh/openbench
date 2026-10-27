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

Usage:
  python -m thesis.ab.step8_gate RUN_DIR PINS_JSON SIDES_JSON [--later]
  python -m thesis.ab.step8_gate --route RUN_DIR
Exit 1 when more than 2 sides fail or fewer than 22 sides were seen
(``--route``: when more than 2 sides are halted).
"""
from __future__ import annotations

import glob
import json
import os
import sys

PROBE_METHODS = ("strace", "embedded")
MAX_OFF_ROUTE_PER_SIDE = 2
MAX_BAD_SIDES = 2


def route_ok(cell: dict) -> bool:
    return str(cell.get("route") or "").startswith("on:")


def _cell_files(run_dir: str):
    for f in sorted(glob.glob(f"{run_dir}/*/cells/*/*/*.json")):
        p = f.split("/")
        yield f, p[-5], p[-3]


def route_check(run_dir: str) -> tuple[dict, int]:
    """Off-route cells to rerun as infra, and sides/batch to halt."""
    off, total = {}, {}
    for f, pr, side in _cell_files(run_dir):
        key = f"{pr}/{side}"
        total[key] = total.get(key, 0) + 1
        c = json.load(open(f))
        if not route_ok(c):
            off.setdefault(key, []).append(
                dict(cell=os.path.relpath(f, run_dir), route=c.get("route") or "off:missing"))
    halted = sorted(k for k, v in off.items() if len(v) > MAX_OFF_ROUTE_PER_SIDE)
    out = dict(cells=sum(total.values()), sides_seen=len(total),
               off_route=off, rerun=[x["cell"] for v in off.values() for x in v],
               label="infra:off_route", halted_sides=halted,
               halt_batch=len(halted) > MAX_BAD_SIDES)
    return out, (1 if out["halt_batch"] else 0)


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


def evaluate(run_dir: str, pins: dict, sides: dict, later: bool = False) -> tuple[dict, int]:
    cells, bad = [], {}
    for f, pr, side in _cell_files(run_dir):
        c = json.load(open(f))
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
