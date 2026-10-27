#!/usr/bin/env python3
"""One-cell-per-side smoke for the post-monorepo step-8 PRs (51062, 53166, 55613).

Runs ``thesis.ab.run_ab`` once per PR with ``--trials 1`` on the PR's first
mapped task, so each of the six sides gets one cell. Those cells run with the
provider bundled in the binary (``thesis/ab/monorepo.py``). The report lists,
per side, the provider-fault count (the D4 rule in
``step8_pins.is_provider_fault``), the agent's call (the checker's
``failure_class``), ``provider_loaded_source``, and the bundled provider
version.

``score_match`` compares the smoke cell's scoring call with the box's
scoring call for the same PR, side, and task, as recorded on main. The box
record is ``<box dir>/<pr>/<side>.jsonl`` under the step-8 box runs
(``DEFAULT_BOX_GLOBS``; ``--box-out`` replaces them). A scoring call is
``pass`` (``failure_class=solved``) or ``fail`` (any other scored class).
Infra cells have no scoring call. The box's call is the majority of its
scored cells (a tie is ``fail``). ``score_match`` is ``true`` only when both
calls exist and are equal; missing box data is ``false``.

A side is ``scorable`` only when its smoke cell exists, loaded the bundled
provider, has zero provider faults, and ``score_match`` is ``true`` (D5 §4).
``step8_pin_dry_run`` recomputes all of that from this table, and also
requires the side to be ready.

Launching needs ``monorepo-builds.csv`` to show a passed control step and a
build record whose binary sha256 matches each side's binary
(``thesis.ab.step8_monorepo_build``).

  python3 -m thesis.ab.step8_monorepo_smoke --cache <opencode-src> --plan
  python3 -m thesis.ab.step8_monorepo_smoke --cache <opencode-src> \\
      --out results/step8-monorepo-smoke-<date> [--box-out <box run dir>]

``--plan`` prints the run_ab commands and exits without a model call. Without
it the smoke calls the model: six cells, one per side.
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

from thesis.ab.monorepo import LOADED_SOURCE, MONOREPO_PRS
from thesis.ab.step8_pins import DEFAULT_OUT, DEFAULT_PRS, ROOT, is_provider_fault

DEFAULT_TASK_MAP = ROOT / "results/step8-full413-1020/task-map.csv"
DEFAULT_SMOKE_CSV = DEFAULT_OUT / "monorepo-smoke.csv"
# The step-8 box runs recorded on main (results/<run>/<pr>/<side>.jsonl).
DEFAULT_BOX_GLOBS = ("results/step8-full413-1020*", "results/step8-sonnet447-pilot-1020-full")
SIDES = ("without", "with")
FIELDS = [
    "pr", "side", "sha", "task", "trial", "cell_present", "call", "success",
    "provider_faults", "provider_loaded_source", "bundled_provider_package",
    "bundled_provider_version", "bundled_provider_tree", "pin_source",
    "smoke_score", "box_cells", "box_scored", "box_solved", "box_score",
    "box_provider_faults", "box_runs", "score_match", "scorable", "reason",
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


def scoring_call(cell: dict) -> str:
    """``pass``, ``fail``, or ``""`` when the cell has no scoring call (infra)."""
    call = cell_call(cell)
    if call == "infra" or call == "unknown":
        return ""
    return "pass" if call == "solved" else "fail"


def box_score(solved: int, scored: int) -> str:
    """The box's scoring call: majority of scored cells; a tie is ``fail``."""
    if scored <= 0:
        return ""
    return "pass" if solved * 2 > scored else "fail"


def score_match(smoke: str, box: str) -> bool:
    """True only when both scoring calls exist and agree."""
    return bool(smoke) and bool(box) and smoke == box


def default_box_dirs(root: Path = ROOT) -> list[Path]:
    found = []
    for pattern in DEFAULT_BOX_GLOBS:
        found.extend(Path(path) for path in sorted(glob.glob(str(Path(root) / pattern))))
    return [path for path in found if path.is_dir()]


def box_summary(box_dirs: list[Path], pr: str, side: str, task: str) -> dict:
    cells = []
    runs = []
    for box in box_dirs:
        found = [
            row for row in _jsonl(Path(box) / pr / f"{side}.jsonl")
            if row.get("task") == task
        ]
        if found:
            runs.append(Path(box).name)
        cells.extend(found)
    calls = [scoring_call(row) for row in cells]
    scored = sum(1 for call in calls if call)
    solved = sum(1 for call in calls if call == "pass")
    faults = sum(1 for row in cells if is_provider_fault(row))
    return {
        "cells": len(cells), "scored": scored, "solved": solved, "faults": faults,
        "score": box_score(solved, scored), "runs": runs,
    }


def assess_side(side: dict, task: str, cell: dict | None, box: dict) -> dict:
    """One report row.

    ``scorable`` needs a cell, a bundled load, zero provider faults, and
    ``score_match`` true against the box's scoring call for this side.
    """
    box_call = box.get("score") or ""
    row = {
        "pr": side["pr"], "side": side["side"], "sha": side["sha"],
        "task": task, "trial": 1,
        "box_cells": box["cells"],
        "box_scored": box.get("scored", 0),
        "box_solved": f"{box['solved']}/{box.get('scored', 0)}" if box.get("scored") else "",
        "box_score": box_call,
        "box_provider_faults": box["faults"] if box["cells"] else "",
        "box_runs": " ".join(box.get("runs") or []),
    }
    reasons = []
    if cell is None:
        row.update({
            "cell_present": "no", "call": "", "success": "", "provider_faults": "",
            "provider_loaded_source": "", "bundled_provider_package": "",
            "bundled_provider_version": "", "bundled_provider_tree": "",
            "pin_source": "", "smoke_score": "", "score_match": "false",
        })
        reasons.append("smoke cell missing")
    else:
        faults = 1 if is_provider_fault(cell) else 0
        call = cell_call(cell)
        loaded = str(cell.get("provider_loaded_source") or "")
        row.update({
            "cell_present": "yes",
            "call": call,
            "success": "" if cell.get("success") is None else str(bool(cell.get("success"))).lower(),
            "provider_faults": faults,
            "provider_loaded_source": loaded,
            "bundled_provider_package": str(cell.get("bundled_provider_package") or ""),
            "bundled_provider_version": str(cell.get("bundled_provider_version") or ""),
            "bundled_provider_tree": str(cell.get("bundled_provider_tree") or ""),
            "pin_source": str(cell.get("pin_source") or ""),
        })
        smoke_call = scoring_call(cell)
        row["smoke_score"] = smoke_call
        matched = score_match(smoke_call, box_call)
        row["score_match"] = "true" if matched else "false"
        if faults:
            reasons.append(f"{faults} provider fault")
        if loaded != LOADED_SOURCE:
            reasons.append(f"provider_loaded_source={loaded or 'unrecorded'}, not {LOADED_SOURCE}")
        if not matched:
            reasons.append(score_mismatch_reason(smoke_call, box_call, box["cells"]))
    row["scorable"] = "no" if reasons else "yes"
    row["reason"] = "; ".join(reasons)
    return row


def score_mismatch_reason(smoke_call: str, box_call: str, box_cells: int) -> str:
    if not box_call:
        if box_cells:
            return "score_match=false: box has no scored cell for this side (all infra)"
        return "score_match=false: no box data for this side on main"
    if not smoke_call:
        return "score_match=false: smoke cell has no scoring call (infra)"
    return f"score_match=false: smoke {smoke_call} != box {box_call}"


def collect(out: Path, sides: list[dict], tasks: dict[str, str], box_dirs: list[Path]) -> list[dict]:
    rows = []
    for side in sides:
        task = tasks[side["pr"]]
        cell = read_smoke_cell(out, side["pr"], side["side"], task)
        rows.append(assess_side(side, task, cell, box_summary(box_dirs, side["pr"], side["side"], task)))
    return rows


def write_report(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def summarize(rows: list[dict]) -> str:
    faults = sum(int(row["provider_faults"] or 0) for row in rows)
    scorable = sum(1 for row in rows if row["scorable"] == "yes")
    lines = [f"sides {len(rows)} provider-faults {faults} scorable {scorable}"]
    for row in rows:
        box = f"{row['box_score']} ({row['box_solved']})" if row["box_score"] else "no box data"
        lines.append(
            f"  {row['pr']} {row['side']:<7} {row['task']}: call={row['call'] or '-'} "
            f"provider_faults={row['provider_faults'] if row['provider_faults'] != '' else '-'} "
            f"loaded={row['provider_loaded_source'] or '-'} "
            f"bundled={row['bundled_provider_version'] or '-'} box={box} "
            f"score_match={row['score_match']} "
            f"scorable={row['scorable']}{' (' + row['reason'] + ')' if row['reason'] else ''}"
        )
    return "\n".join(lines)


def load_smoke(path: Path) -> dict[tuple[str, str], dict]:
    """``(pr, side)`` -> report row, or ``{}`` when the smoke has not run."""
    path = Path(path)
    if not path.is_file():
        return {}
    with path.open(newline="") as fh:
        return {(row["pr"], row["side"]): row for row in csv.DictReader(fh)}


def smoke_scorable(entry: dict | None) -> tuple[bool, str]:
    """``(scorable, reason)`` for one side from the smoke table.

    Re-derived from the counts and the two scoring calls, not only the
    ``scorable`` or ``score_match`` columns, so a hand-edited table cannot
    mark a side with a provider fault or a mismatched call scorable.
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
    smoke_call = str(entry.get("smoke_score") or "")
    box_call = str(entry.get("box_score") or "")
    if not score_match(smoke_call, box_call):
        try:
            box_cells = int(entry.get("box_cells") or 0)
        except ValueError:
            box_cells = 0
        return False, score_mismatch_reason(smoke_call, box_call, box_cells)
    if entry.get("score_match") != "true":
        return False, "smoke score_match is not true"
    if entry.get("scorable") != "yes":
        return False, entry.get("reason") or "smoke did not mark the side scorable"
    return True, ""


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
    parser.add_argument("--box-out", type=Path, action="append", default=[],
                        help="box run directory (<dir>/<pr>/<side>.jsonl); replaces the step-8 box runs on main")
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
    rows = collect(args.out, sides, tasks, args.box_out or default_box_dirs())
    write_report(rows, args.report)
    print(summarize(rows))
    print(f"wrote {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
