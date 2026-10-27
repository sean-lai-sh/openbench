#!/usr/bin/env python3
"""Scoring parity: replay the box's saved cell outputs through this runner's scoring path.

The D5 §4 bar for the post-monorepo PRs (51062, 53166, 55613) is that the new
runner scores like the box. This check takes every cell of PRs the box already
scored, replays each cell's saved outputs through the scoring code this
branch uses (``obench.run`` / ``obench.checker_verdict`` /
``obench.failure_class``, then ``thesis.ab.watch.apply_watchdog_class`` as
``run_ab.execute_cell`` does), and requires the replayed pass/fail **and**
``failure_class`` to equal the box's on 100% of cells. It reads saved
outputs only: no model calls, no checker re-run, no GCP.

Replay per cell, in the order ``obench.run.run_cell`` and then
``run_ab.execute_cell`` apply it:

1. Drop the box's verdict fields (``success``, ``score``, ``failure_class``,
   ``failure_reason``).
2. Parse ``raw_score`` from the saved ``checker_stdout`` with the runner's
   ``StreamingScoreParser``.
3. If the checker ran (``checker_exit`` recorded): thesis tasks
   (``expects_explicit_verdict``) go through ``apply_explicit_verdict``;
   other tasks use the exit-code rule plus ``classify_failure``. If the
   checker never ran, only ``classify_failure`` applies.
4. ``apply_watchdog_class``: a watchdog marker in ``error`` /
   ``output_tail`` (``openbench-infra:no_progress ...``) discards the checker
   score; after real model requests it is a scored ``hang``, otherwise infra.
5. The call is ``pass`` when the replayed ``failure_class`` is ``solved``,
   otherwise ``fail``. The box's call comes from its recorded
   ``failure_class`` the same way.

Default inputs (180 cells):

- ``results/step8-full413-1020-F03-1-rerun`` PRs 3006 (``make-it-run``) and
  3079 (``taskflow``): the latest batch the box scored; its ``RERUN.txt``
  lists 2986, 3006 and 3079 as complete (3185 is partial and unscored), and
  these are the last two complete ones. 120 cells, all solved.
- ``results/step8-full413-1020-F01`` PR 579 (``trig-read-lines``): 0/30 on
  both sides, all ``hang`` (no-progress watchdog after model requests, with
  the checker passing on the workspace). 60 fail cells, so the check covers
  fails and the watchdog step, not only passes. 579 without trial 27 is
  relabeled infra by the #155 rescore only in ``overrides.csv``
  (``label_only``); its saved row, which is what the box recorded, says
  ``hang``.

``--source <box run dir>:<pr>`` (repeatable) replaces the defaults.

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
F01_BOX_RUN = ROOT / "results" / "step8-full413-1020-F01"
# (box run directory, PR). Every cell of each is replayed.
DEFAULT_SOURCES = (
    (DEFAULT_BOX_RUN, "3006"),
    (DEFAULT_BOX_RUN, "3079"),
    (F01_BOX_RUN, "579"),
)
EXPECTED_CELLS = 180
DEFAULT_PARITY_CSV = DEFAULT_OUT / "scoring-parity.csv"
SIDES = ("without", "with")
VERDICT_FIELDS = ("success", "score", "failure_class", "failure_reason")
FIELDS = [
    "box_run", "pr", "side", "task", "trial", "checker_exit",
    "box_failure_class", "replay_failure_class", "box_call", "replay_call",
    "call_match", "class_match", "match",
]


def call_of(failure_class) -> str:
    return "pass" if str(failure_class or "") == "solved" else "fail"


def replay_cell(saved: dict, tasks_dir: Path | None = None) -> dict:
    """Score one saved box cell again with this runner's scoring path.

    Returns a copy of the row with ``success``, ``score``, ``failure_class``
    and ``failure_reason`` recomputed. ``saved`` is not changed.
    """
    row = _replay_checker(saved, tasks_dir)
    from thesis.ab.watch import apply_watchdog_class
    apply_watchdog_class(row)
    return row


def _replay_checker(saved: dict, tasks_dir: Path | None) -> dict:
    """Steps 1-3: ``obench.run.run_cell`` after the agent returns."""
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


def run_parity(sources, tasks_dir: Path | None = None) -> list[dict]:
    """Replay every cell of each ``(box run, pr)`` in ``sources``."""
    rows = []
    for box_run, pr in sources:
        for side, saved in box_cells(box_run, pr):
            replayed = replay_cell(saved, tasks_dir)
            box_call = call_of(saved.get("failure_class"))
            replay_call = call_of(replayed.get("failure_class"))
            box_class = saved.get("failure_class") or ""
            replay_class = replayed.get("failure_class") or ""
            call_match = box_call == replay_call
            class_match = bool(box_class) and box_class == replay_class
            rows.append({
                "box_run": Path(box_run).name, "pr": pr, "side": side,
                "task": saved.get("task") or "", "trial": saved.get("trial"),
                "checker_exit": "" if saved.get("checker_exit") is None else saved.get("checker_exit"),
                "box_failure_class": saved.get("failure_class") or "",
                "replay_failure_class": replayed.get("failure_class") or "",
                "box_call": box_call, "replay_call": replay_call,
                "call_match": "true" if call_match else "false",
                "class_match": "true" if class_match else "false",
                "match": "true" if call_match and class_match else "false",
            })
    return rows


def _source_key(row: dict) -> tuple[str, str]:
    return str(row.get("box_run") or ""), str(row.get("pr") or "")


def parity_result(rows: list[dict], sources=None, expected_cells: int | None = None) -> tuple[bool, str]:
    """``(passed, reason)``. Recomputed from the box and replayed calls and classes.

    Passes only when there are cells for every source (and at least two
    PRs), the cell count is ``expected_cells`` when given, and every cell's
    replayed pass/fail and ``failure_class`` equal the box's. The ``match``
    columns are not trusted.
    """
    if not rows:
        return False, "scoring parity not run"
    found = sorted({_source_key(row) for row in rows})
    wanted = sorted((Path(run).name, str(pr)) for run, pr in sources) if sources else found
    if len({pr for _run, pr in wanted}) < 2:
        return False, f"scoring parity needs 2 PRs, has {len({pr for _run, pr in wanted})}"
    missing = [f"{run}:{pr}" for run, pr in wanted if (run, pr) not in found]
    if missing:
        return False, f"scoring parity has no cells for {', '.join(missing)}"
    if expected_cells is not None and len(rows) != expected_cells:
        return False, f"scoring parity has {len(rows)} cells, expected {expected_cells}"
    bad = [
        row for row in rows
        if not row.get("box_call") or row.get("box_call") != row.get("replay_call")
        or not row.get("box_failure_class")
        or row.get("box_failure_class") != row.get("replay_failure_class")
    ]
    if bad:
        first = bad[0]
        return False, (
            f"scoring parity {len(rows) - len(bad)}/{len(rows)} cells: e.g. {first.get('pr')} "
            f"{first.get('side')} trial {first.get('trial')} box {first.get('box_call') or '?'}/"
            f"{first.get('box_failure_class') or '?'} != replay {first.get('replay_call') or '?'}/"
            f"{first.get('replay_failure_class') or '?'}"
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


def default_parity_from_table(path: Path) -> tuple[bool, str]:
    """The committed table checked against the default sources and 180 cells."""
    return parity_result(load_parity(path), DEFAULT_SOURCES, EXPECTED_CELLS)


def summarize(rows: list[dict]) -> str:
    passed, reason = parity_result(rows)
    lines = []
    for key in sorted({_source_key(row) for row in rows}, key=lambda item: (item[0], int(item[1]) if item[1].isdigit() else 0)):
        cells = [row for row in rows if _source_key(row) == key]
        agree = sum(1 for row in cells if row["match"] == "true")
        passes = sum(1 for row in cells if row["box_call"] == "pass")
        classes = ", ".join(f"{name}={count}" for name, count in sorted(
            {c: sum(1 for row in cells if row["box_failure_class"] == c) for c in {r["box_failure_class"] for r in cells}}.items()
        ))
        lines.append(
            f"  {key[0]} {key[1]}: {agree}/{len(cells)} cells match on call and class "
            f"(box pass {passes}, fail {len(cells) - passes}; {classes})"
        )
    agree = sum(row["match"] == "true" for row in rows)
    head = f"scoring_parity {'pass' if passed else 'fail'}: {agree}/{len(rows)} cells"
    return "\n".join([head + (f" ({reason})" if reason else ""), *lines])


def _source_arg(text: str) -> tuple[Path, str]:
    run, sep, pr = text.rpartition(":")
    if not sep or not run or not pr:
        raise argparse.ArgumentTypeError(f"expected <box run dir>:<pr>, got {text!r}")
    return Path(run), pr


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay box cell outputs through this runner's scoring path")
    parser.add_argument("--source", type=_source_arg, action="append", default=[],
                        help="<box run dir>:<pr> to replay (repeatable); default: F03-1-rerun 3006 and 3079, F01 579")
    parser.add_argument("--out", type=Path, default=DEFAULT_PARITY_CSV)
    args = parser.parse_args(argv)
    sources = tuple(args.source) or DEFAULT_SOURCES
    expected = None if args.source else EXPECTED_CELLS
    rows = run_parity(sources)
    write_parity(rows, args.out)
    print(summarize(rows))
    print(f"wrote {args.out}")
    passed, reason = parity_result(rows, sources, expected)
    if not passed:
        print(reason, file=sys.stderr)
    return 0 if passed else 3


if __name__ == "__main__":
    sys.exit(main())
