#!/usr/bin/env python3
"""One-cell-per-side smoke for the post-monorepo step-8 PRs (51062, 53166, 55613).

Runs ``thesis.ab.run_ab`` once per PR with ``--trials 1`` on the PR's first
mapped task, so each of the six sides gets one cell. Those cells run with the
provider bundled in the binary (``thesis/ab/monorepo.py``). The report lists,
per side, the provider-fault count (the D4 rule in
``step8_pins.is_provider_fault``), the agent's call (the checker's
``failure_class``), ``provider_loaded_source``, and the bundled provider
version.

The three PRs are scorable together or not at all (D5 §4): all six smoke
cells must exist, load the bundled provider, and have zero provider faults,
and ``scoring_parity`` must pass. ``scoring_parity`` is the replay of the
box's saved outputs for two PRs it already scored through this runner's
scoring path (``thesis.ab.step8_scoring_parity``,
``data/step8-pins/scoring-parity.csv``): 100% of cells must reproduce the
box's pass/fail. Otherwise every side is ``scorable=excluded``.
``step8_pin_dry_run`` recomputes this from the two tables.

Launching needs ``monorepo-builds.csv`` to show a passed control step and a
build record whose binary sha256 matches each side's binary
(``thesis.ab.step8_monorepo_build``).

  python3 -m thesis.ab.step8_monorepo_smoke --cache <opencode-src> --plan
  python3 -m thesis.ab.step8_monorepo_smoke --cache <opencode-src> \\
      --out results/step8-monorepo-smoke-<date>

``--plan`` prints the run_ab commands and exits without a model call. Without
it the smoke calls the model: six cells, one per side.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

from thesis.ab.monorepo import LOADED_SOURCE, MONOREPO_PRS
from thesis.ab.step8_pins import DEFAULT_OUT, DEFAULT_PRS, ROOT, is_provider_fault

DEFAULT_TASK_MAP = ROOT / "results/step8-full413-1020/task-map.csv"
DEFAULT_SMOKE_CSV = DEFAULT_OUT / "monorepo-smoke.csv"
SIDES = ("without", "with")
SCORABLE = "yes"
EXCLUDED = "excluded"
FIELDS = [
    "pr", "side", "sha", "task", "trial", "cell_present", "call", "success",
    "provider_faults", "provider_loaded_source", "bundled_provider_package",
    "bundled_provider_version", "bundled_provider_tree", "pin_source",
    "smoke_ok", "scoring_parity", "scorable", "reason",
]


def monorepo_sides(pins_csv: Path) -> list[dict]:
    """The six monorepo sides from ``pins.csv``, without before with."""
    rows = []
    with Path(pins_csv).open(newline="") as fh:
        for row in csv.DictReader(fh):
            if row["pr"] in MONOREPO_PRS:
                rows.append({"pr": row["pr"], "side": row["side"], "sha": row["sha"]})
    rows.sort(key=lambda row: (MONOREPO_PRS.index(row["pr"]), SIDES.index(row["side"])))
    return rows


def first_tasks(task_map: Path) -> dict[str, str]:
    """PR -> first mapped task, for the monorepo PRs."""
    found: dict[str, str] = {}
    with Path(task_map).open(newline="") as fh:
        for row in csv.DictReader(fh):
            pr = str(row.get("pr") or "").strip()
            task = str(row.get("task") or "").strip()
            if pr in MONOREPO_PRS and task and pr not in found:
                found[pr] = task
    missing = [pr for pr in MONOREPO_PRS if pr not in found]
    if missing:
        raise SystemExit(f"no mapped task for {', '.join(missing)} in {task_map}")
    return found


def smoke_commands(
    *,
    prs: Path,
    task_map: Path,
    tasks: dict[str, str],
    out: Path,
    cache: Path,
    model: str,
    python: str = sys.executable,
) -> list[list[str]]:
    """One run_ab command per PR: one trial, both sides, one task."""
    commands = []
    for pr in MONOREPO_PRS:
        commands.append([
            python, "-m", "thesis.ab.run_ab", str(prs),
            "--pr", pr,
            "--task-map", str(task_map),
            "--tasks", tasks[pr],
            "--trials", "1",
            "--jobs", "2",
            "--order", "interleave",
            "--model", model,
            "--cell-meta",
            "--out", str(out),
            "--cache", str(cache),
        ])
    return commands


def _cell_path(out: Path, pr: str, side: str, task: str, trial: int) -> Path:
    # Same layout as run_ab.cell_file; not imported so tests stay light.
    return Path(out) / pr / "cells" / side / task.replace("/", "__") / f"{trial}.json"


def _jsonl(path: Path) -> list[dict]:
    rows = []
    if not path.is_file():
        return rows
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                parsed = json.loads(line)
            except ValueError:
                continue
            if isinstance(parsed, dict):
                rows.append(parsed)
    return rows


def read_smoke_cell(out: Path, pr: str, side: str, task: str, trial: int = 1) -> dict | None:
    path = _cell_path(out, pr, side, task, trial)
    if path.is_file():
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            parsed = None
        if isinstance(parsed, dict):
            return parsed
    rows = [
        row for row in _jsonl(Path(out) / pr / f"{side}.jsonl")
        if row.get("task") == task and int(row.get("trial") or 0) == trial
    ]
    return rows[-1] if rows else None


def cell_call(cell: dict) -> str:
    """The agent's call as the checker scored it: ``failure_class``."""
    failure = str(cell.get("failure_class") or "").strip()
    if failure:
        return failure
    if cell.get("success") is True:
        return "solved"
    if cell.get("success") is False:
        return "failed"
    return "unknown"


def assess_side(side: dict, task: str, cell: dict | None) -> dict:
    """One report row. ``smoke_ok`` needs a cell, a bundled load, and zero provider faults."""
    row = {"pr": side["pr"], "side": side["side"], "sha": side["sha"], "task": task, "trial": 1}
    reasons = []
    if cell is None:
        row.update({
            "cell_present": "no", "call": "", "success": "", "provider_faults": "",
            "provider_loaded_source": "", "bundled_provider_package": "",
            "bundled_provider_version": "", "bundled_provider_tree": "", "pin_source": "",
        })
        reasons.append("smoke cell missing")
    else:
        faults = 1 if is_provider_fault(cell) else 0
        loaded = str(cell.get("provider_loaded_source") or "")
        row.update({
            "cell_present": "yes",
            "call": cell_call(cell),
            "success": "" if cell.get("success") is None else str(bool(cell.get("success"))).lower(),
            "provider_faults": faults,
            "provider_loaded_source": loaded,
            "bundled_provider_package": str(cell.get("bundled_provider_package") or ""),
            "bundled_provider_version": str(cell.get("bundled_provider_version") or ""),
            "bundled_provider_tree": str(cell.get("bundled_provider_tree") or ""),
            "pin_source": str(cell.get("pin_source") or ""),
        })
        if faults:
            reasons.append(f"{faults} provider fault")
        if loaded != LOADED_SOURCE:
            reasons.append(f"provider_loaded_source={loaded or 'unrecorded'}, not {LOADED_SOURCE}")
    row["smoke_ok"] = "no" if reasons else "yes"
    row["reason"] = "; ".join(reasons)
    return row


def smoke_side_ok(entry: dict | None) -> tuple[bool, str]:
    """``(ok, reason)`` for one side, recomputed from the table's counts.

    A hand-edited ``smoke_ok`` or ``scorable`` column cannot hide a provider
    fault or a load that was not bundled.
    """
    if not entry:
        return False, "smoke not run"
    if entry.get("cell_present") != "yes":
        return False, "smoke cell missing"
    try:
        faults = int(entry.get("provider_faults") or 0)
    except ValueError:
        return False, "smoke provider_faults unreadable"
    if faults:
        return False, f"smoke shows {faults} provider fault"
    if entry.get("provider_loaded_source") != LOADED_SOURCE:
        return False, f"smoke provider_loaded_source={entry.get('provider_loaded_source') or 'unrecorded'}"
    return True, ""


def group_decision(
    smoke: dict[tuple[str, str], dict],
    sides: list[dict],
    parity: tuple[bool, str],
) -> tuple[bool, list[str]]:
    """Scorable for all three PRs, or excluded, plus the reasons.

    Needs a smoke row for every one of the six sides with ``smoke_side_ok``
    and ``scoring_parity`` passing.
    """
    reasons = []
    for side in sides:
        ok, why = smoke_side_ok(smoke.get((side["pr"], side["side"])))
        if not ok:
            reasons.append(f"{side['pr']} {side['side']}: {why}")
    if len(sides) != 2 * len(MONOREPO_PRS):
        reasons.append(f"expected {2 * len(MONOREPO_PRS)} sides, found {len(sides)}")
    parity_ok, parity_reason = parity
    if not parity_ok:
        reasons.append(parity_reason or "scoring parity failed")
    return not reasons, reasons


def apply_group(rows: list[dict], sides: list[dict], parity: tuple[bool, str]) -> list[dict]:
    """Stamp ``scoring_parity`` and the all-or-nothing ``scorable`` on each row."""
    smoke = {(row["pr"], row["side"]): row for row in rows}
    ok, reasons = group_decision(smoke, sides, parity)
    for row in rows:
        row["scoring_parity"] = "pass" if parity[0] else "fail"
        row["scorable"] = SCORABLE if ok else EXCLUDED
        if not ok:
            row["reason"] = "; ".join(
                part for part in (row.get("reason") or "", "excluded: " + "; ".join(reasons)) if part
            )
    return rows


def collect(out: Path, sides: list[dict], tasks: dict[str, str], parity: tuple[bool, str]) -> list[dict]:
    rows = []
    for side in sides:
        task = tasks[side["pr"]]
        rows.append(assess_side(side, task, read_smoke_cell(out, side["pr"], side["side"], task)))
    return apply_group(rows, sides, parity)


def write_report(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows({key: row.get(key, "") for key in FIELDS} for row in rows)


def summarize(rows: list[dict]) -> str:
    faults = sum(int(row["provider_faults"] or 0) for row in rows)
    status = rows[0]["scorable"] if rows else EXCLUDED
    parity = rows[0]["scoring_parity"] if rows else "fail"
    lines = [f"sides {len(rows)} provider-faults {faults} scoring_parity {parity} -> {status}"]
    for row in rows:
        lines.append(
            f"  {row['pr']} {row['side']:<7} {row['task']}: call={row['call'] or '-'} "
            f"provider_faults={row['provider_faults'] if row['provider_faults'] != '' else '-'} "
            f"loaded={row['provider_loaded_source'] or '-'} "
            f"bundled={row['bundled_provider_version'] or '-'} smoke_ok={row['smoke_ok']}"
        )
    if status != SCORABLE and rows:
        lines.append(f"  {rows[0]['reason'].split('excluded: ', 1)[-1]}")
    return "\n".join(lines)


def load_smoke(path: Path) -> dict[tuple[str, str], dict]:
    """``(pr, side)`` -> report row, or ``{}`` when the smoke has not run."""
    path = Path(path)
    if not path.is_file():
        return {}
    with path.open(newline="") as fh:
        return {(row["pr"], row["side"]): row for row in csv.DictReader(fh)}


def run_smoke(
    commands: list[list[str]],
    runner: Callable[[list[str]], int] | None = None,
) -> list[int]:
    run = runner or (lambda cmd: subprocess.run(cmd, cwd=str(ROOT), check=False).returncode)
    return [run(cmd) for cmd in commands]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="One-cell-per-side monorepo smoke")
    parser.add_argument("--cache", type=Path, required=True,
                        help="OpenCode build cache (<opencode-src>, holds bin/<sha>/opencode and worktrees/)")
    parser.add_argument("--out", type=Path, default=ROOT / "results" / "step8-monorepo-smoke")
    parser.add_argument("--prs", type=Path, default=DEFAULT_PRS)
    parser.add_argument("--task-map", type=Path, default=DEFAULT_TASK_MAP)
    parser.add_argument("--pins", type=Path, default=DEFAULT_OUT / "pins.csv")
    parser.add_argument("--model", default="claude-sonnet-5-5")
    parser.add_argument("--parity", type=Path, default=None,
                        help="scoring parity table (default data/step8-pins/scoring-parity.csv)")
    parser.add_argument("--builds", type=Path, default=None,
                        help="build records (default data/step8-pins/monorepo-builds.csv)")
    parser.add_argument("--report", type=Path, default=DEFAULT_SMOKE_CSV)
    parser.add_argument("--plan", action="store_true", help="print the run_ab commands; no model call")
    parser.add_argument("--collect-only", action="store_true",
                        help="do not launch; rebuild the report from cells already under --out")
    args = parser.parse_args(argv)
    sides = monorepo_sides(args.pins)
    tasks = first_tasks(args.task_map)
    commands = smoke_commands(
        prs=args.prs, task_map=args.task_map, tasks=tasks,
        out=args.out, cache=args.cache, model=args.model,
    )
    if args.plan:
        for cmd in commands:
            print(" ".join(cmd))
        return 0
    if not args.collect_only:
        from thesis.ab.step8_monorepo_build import DEFAULT_BUILDS_CSV, launch_gate
        problems = launch_gate(args.builds or DEFAULT_BUILDS_CSV, sides, args.cache)
        if problems:
            for problem in problems:
                print(f"build gate: {problem}", file=sys.stderr)
            print("refusing to launch: no rebuilt binary is used until the build gate passes",
                  file=sys.stderr)
            return 3
        codes = run_smoke(commands)
        for cmd, code in zip(commands, codes):
            if code:
                print(f"run_ab exited {code}: {' '.join(cmd)}", file=sys.stderr)
    from thesis.ab.step8_scoring_parity import DEFAULT_PARITY_CSV, default_parity_from_table
    rows = collect(args.out, sides, tasks, default_parity_from_table(args.parity or DEFAULT_PARITY_CSV))
    write_report(rows, args.report)
    print(summarize(rows))
    print(f"wrote {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
