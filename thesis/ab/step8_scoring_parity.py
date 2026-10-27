#!/usr/bin/env python3
"""Scoring parity: replay the box's saved cell outputs through this runner's scoring path.

The D5 §4 bar for the post-monorepo PRs (51062, 53166, 55613) is that the new
runner scores like the box. This check takes every cell of two PRs the box
already scored, replays each cell's saved outputs through the scoring code
this branch uses (``obench.run`` / ``obench.checker_verdict`` /
``obench.failure_class``), and requires the replayed pass/fail to equal the
box's recorded pass/fail on 100% of cells. It reads saved outputs only: no
model calls, no checker re-run, no GCP.

Replay per cell, matching the order in ``obench.run`` after the checker
returns:

1. Drop the box's verdict fields (``success``, ``score``, ``failure_class``,
   ``failure_reason``).
2. Parse ``raw_score`` from the saved ``checker_stdout`` with the runner's
   ``StreamingScoreParser``.
3. If the checker ran (``checker_exit`` recorded): thesis tasks
   (``expects_explicit_verdict``) go through ``apply_explicit_verdict``;
   other tasks use the exit-code rule plus ``classify_failure``. If the
   checker never ran, only ``classify_failure`` applies.
4. The call is ``pass`` when the replayed ``failure_class`` is ``solved``,
   otherwise ``fail``. The box's call comes from its recorded
   ``failure_class`` the same way.

Default inputs: the latest batch the box scored is
``results/step8-full413-1020-F03-1-rerun``. Its ``RERUN.txt`` lists 2986,
3006 and 3079 as complete (3185 has one partial cell and is unscored). The two
PRs are the last two complete ones, 3006 (``make-it-run``) and 3079
(``taskflow``), 120 cells in all. ``--box-run`` and ``--pr`` override.

  python3 -m thesis.ab.step8_scoring_parity

Writes ``data/step8-pins/scoring-parity.csv`` (one row per cell) and exits
nonzero when parity fails.
"""
from __future__ import annotations

import argparse
import copy
import csv
import json
import sys
from pathlib import Path

from thesis.ab.step8_pins import DEFAULT_OUT, ROOT

DEFAULT_BOX_RUN = ROOT / "results" / "step8-full413-1020-F03-1-rerun"
DEFAULT_PRS = ("3006", "3079")
DEFAULT_PARITY_CSV = DEFAULT_OUT / "scoring-parity.csv"
SIDES = ("without", "with")
VERDICT_FIELDS = ("success", "score", "failure_class", "failure_reason")
FIELDS = [
    "box_run", "pr", "side", "task", "trial", "checker_exit",
    "box_failure_class", "replay_failure_class", "box_call", "replay_call", "match",
]


def call_of(failure_class) -> str:
    return "pass" if str(failure_class or "") == "solved" else "fail"


def replay_cell(saved: dict, tasks_dir: Path | None = None) -> dict:
    """Score one saved box cell again with this runner's scoring path.

    Returns a copy of the row with ``success``, ``score``, ``failure_class``
    and ``failure_reason`` recomputed. ``saved`` is not changed.
    """
    from obench.checker_verdict import apply_explicit_verdict, expects_explicit_verdict, repo_tasks_dir
    from obench.failure_class import classify_failure, classify_failure_reason
    from obench.run import StreamingScoreParser

    row = copy.deepcopy(saved)
    for key in VERDICT_FIELDS:
        row.pop(key, None)
    output = str(row.get("output_tail") or "")
    timeout_s = row.get("timeout_s")
    checker_exit = row.get("checker_exit")
    if checker_exit is None:
        row["success"] = False
        row["failure_class"] = classify_failure(row, output, timeout_s)
        row["failure_reason"] = classify_failure_reason(row, output)
        return row
    parser = StreamingScoreParser()
    parser.feed(str(row.get("checker_stdout") or ""))
    raw_score = parser.close()
    task_dir = Path(tasks_dir or repo_tasks_dir()) / str(row.get("task") or "")
    if expects_explicit_verdict(str(task_dir)):
        apply_explicit_verdict(
            row, checker_exit, raw_score, classify_failure, classify_failure_reason,
            output, timeout_s,
        )
        return row
    row["success"] = checker_exit == 0
    row["score"] = 1.0 if checker_exit == 0 else (raw_score if raw_score is not None else 0.0)
    row["failure_class"] = classify_failure(row, output, timeout_s)
    row["failure_reason"] = classify_failure_reason(row, output)
    return row


def box_cells(box_run: Path, pr: str) -> list[tuple[str, dict]]:
    """Every saved cell row the box wrote for ``pr``, as ``(side, row)``."""
    out = []
    for side in SIDES:
        path = Path(box_run) / pr / f"{side}.jsonl"
        if not path.is_file():
            continue
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if isinstance(row, dict) and "cell_seed" in row:
                    out.append((side, row))
    return out


def run_parity(box_run: Path, prs, tasks_dir: Path | None = None) -> list[dict]:
    rows = []
    for pr in prs:
        for side, saved in box_cells(box_run, pr):
            replayed = replay_cell(saved, tasks_dir)
            box_call = call_of(saved.get("failure_class"))
            replay_call = call_of(replayed.get("failure_class"))
            rows.append({
                "box_run": Path(box_run).name, "pr": pr, "side": side,
                "task": saved.get("task") or "", "trial": saved.get("trial"),
                "checker_exit": "" if saved.get("checker_exit") is None else saved.get("checker_exit"),
                "box_failure_class": saved.get("failure_class") or "",
                "replay_failure_class": replayed.get("failure_class") or "",
                "box_call": box_call, "replay_call": replay_call,
                "match": "true" if box_call == replay_call else "false",
            })
    return rows


def parity_result(rows: list[dict], prs=None) -> tuple[bool, str]:
    """``(passed, reason)``. Recomputed from ``box_call`` and ``replay_call``.

    Passes only when there are cells for every PR (and at least two PRs) and
    every cell's replayed call equals the box's.
    """
    if not rows:
        return False, "scoring parity not run"
    found = sorted({str(row.get("pr") or "") for row in rows})
    wanted = sorted(str(pr) for pr in prs) if prs else found
    if len(wanted) < 2:
        return False, f"scoring parity needs 2 PRs, has {len(wanted)}"
    missing = [pr for pr in wanted if pr not in found]
    if missing:
        return False, f"scoring parity has no cells for {', '.join(missing)}"
    bad = [
        row for row in rows
        if not row.get("box_call") or row.get("box_call") != row.get("replay_call")
    ]
    if bad:
        first = bad[0]
        return False, (
            f"scoring parity {len(rows) - len(bad)}/{len(rows)} cells: e.g. {first.get('pr')} "
            f"{first.get('side')} trial {first.get('trial')} box {first.get('box_call') or '?'} "
            f"!= replay {first.get('replay_call') or '?'}"
        )
    return True, ""


def write_parity(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows({key: row.get(key, "") for key in FIELDS} for row in rows)


def load_parity(path: Path) -> list[dict]:
    path = Path(path)
    if not path.is_file():
        return []
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def parity_from_table(path: Path) -> tuple[bool, str]:
    return parity_result(load_parity(path))


def summarize(rows: list[dict]) -> str:
    passed, reason = parity_result(rows)
    lines = []
    for pr in sorted({row["pr"] for row in rows}):
        cells = [row for row in rows if row["pr"] == pr]
        agree = sum(1 for row in cells if row["match"] == "true")
        passes = sum(1 for row in cells if row["box_call"] == "pass")
        lines.append(f"  {pr}: {agree}/{len(cells)} cells match (box pass {passes}, fail {len(cells) - passes})")
    head = f"scoring_parity {'pass' if passed else 'fail'}: {sum(r['match'] == 'true' for r in rows)}/{len(rows)} cells"
    return "\n".join([head + (f" ({reason})" if reason else ""), *lines])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay box cell outputs through this runner's scoring path")
    parser.add_argument("--box-run", type=Path, default=DEFAULT_BOX_RUN)
    parser.add_argument("--pr", action="append", default=[], help=f"PR to replay (default {', '.join(DEFAULT_PRS)})")
    parser.add_argument("--out", type=Path, default=DEFAULT_PARITY_CSV)
    args = parser.parse_args(argv)
    prs = tuple(args.pr) or DEFAULT_PRS
    rows = run_parity(args.box_run, prs)
    write_parity(rows, args.out)
    print(summarize(rows))
    print(f"wrote {args.out}")
    passed, _reason = parity_result(rows, prs)
    return 0 if passed else 3


if __name__ == "__main__":
    sys.exit(main())
