"""Mark whether a saved cell exercised a pull request's evidence pattern.

The A/B runner keeps a transcript plus the copied OpenCode storage and logs
for each cell. This module greps those files with the pattern from
``thesis/ab/fixtures/trigger-evidence.csv`` and writes ``exercised`` on the cell:

- ``exercised`` when a transcript or copied storage/log matches
- ``not exercised`` when those files exist and none match
- ``undeterminable`` when no evidence file is present

It also writes ``evidence-summary.json`` with a count per PR and side.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from thesis.ab.durable import publish_text
from thesis.ab.run_ab import read_cell, task_component

EXERCISED = "exercised"
NOT_EXERCISED = "not exercised"
UNDETERMINABLE = "undeterminable"
_STATUSES = (EXERCISED, NOT_EXERCISED, UNDETERMINABLE)
_MAX_BYTES = 32 * 1024 * 1024
# Researcher's pattern table, committed next to this module.
DEFAULT_PATTERNS = Path(__file__).resolve().parent / "fixtures" / "trigger-evidence.csv"


class EvidenceError(ValueError):
    pass


@dataclass(frozen=True)
class EvidencePattern:
    pr: str
    task: str
    pattern: str
    compiled: re.Pattern[str]


def load_patterns(path: Path) -> dict[str, EvidencePattern]:
    path = Path(path)
    if not path.is_file():
        raise EvidenceError(f"evidence pattern file not found: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise EvidenceError(f"evidence pattern file not readable: {path}: {exc}") from exc
    reader = csv.DictReader(text.splitlines())
    fields = set(reader.fieldnames or [])
    missing = {"pr", "task", "evidence_pattern"} - fields
    if missing:
        raise EvidenceError(f"{path}: missing column(s): {', '.join(sorted(missing))}")
    found: dict[str, EvidencePattern] = {}
    for index, row in enumerate(reader, start=2):
        pr = str(row.get("pr") or "").strip()
        if not pr:
            raise EvidenceError(f"{path}:{index}: missing pr")
        if pr in found:
            raise EvidenceError(f"{path}:{index}: duplicate PR {pr}")
        pattern = str(row.get("evidence_pattern") or "")
        if not pattern:
            raise EvidenceError(f"{path}:{index}: missing evidence_pattern")
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise EvidenceError(f"{path}:{index}: evidence_pattern does not compile: {exc}") from exc
        found[pr] = EvidencePattern(
            pr=pr,
            task=str(row.get("task") or "").strip(),
            pattern=pattern,
            compiled=compiled,
        )
    if not found:
        raise EvidenceError(f"{path}: no evidence rows")
    return found


def _header_matches(path: Path, task: str, trial: int) -> bool:
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:800]
    except OSError:
        return False
    return f"task={task} trial={trial}" in head


def transcript_files(out_dir: Path, pr: str, side: str, task: str, trial: int, row: dict) -> list[Path]:
    root = out_dir / pr / "transcripts" / side
    found: list[Path] = []
    run_id = row.get("run_id")
    if isinstance(run_id, str) and run_id.strip():
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", run_id)
        candidate = root / f"{safe}.txt"
        if candidate.is_file():
            found.append(candidate)
    if root.is_dir():
        for path in sorted(root.glob("*.txt")):
            if path in found:
                continue
            if _header_matches(path, task, trial):
                found.append(path)
    return found


def evidence_files(out_dir: Path, pr: str, side: str, task: str, trial: int) -> list[Path]:
    root = out_dir / pr / "transcripts" / side / task_component(task) / str(trial)
    if not root.is_dir():
        return []
    return [path for path in sorted(root.rglob("*")) if path.is_file()]


def file_matches(path: Path, pattern: re.Pattern[str]) -> bool:
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if size > _MAX_BYTES:
        return False
    try:
        data = path.read_bytes()
    except OSError:
        return False
    # Latin-1 keeps every byte. Without DOTALL, `.` stays on one line, which
    # matches the line-oriented patterns checked with grep -E.
    text = data.decode("latin-1")
    return pattern.search(text) is not None


def classify_files(paths: list[Path], pattern: re.Pattern[str]) -> str:
    if not paths:
        return UNDETERMINABLE
    for path in paths:
        if file_matches(path, pattern):
            return EXERCISED
    return NOT_EXERCISED


def iter_cells(out_dir: Path):
    root = Path(out_dir)
    if not root.is_dir():
        return
    for pr_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        cells = pr_dir / "cells"
        if not cells.is_dir():
            continue
        for side_dir in sorted(path for path in cells.iterdir() if path.is_dir()):
            for task_dir in sorted(path for path in side_dir.iterdir() if path.is_dir()):
                for trial_path in sorted(task_dir.glob("*.json")):
                    if not trial_path.stem.isdigit():
                        continue
                    row = read_cell(trial_path)
                    if row is None:
                        continue
                    yield pr_dir.name, side_dir.name, task_dir.name, int(trial_path.stem), trial_path, row


def _empty_counts() -> dict[str, int]:
    return {status: 0 for status in _STATUSES}


def annotate(out_dir: Path, patterns: dict[str, EvidencePattern]) -> dict:
    """Write ``exercised`` on each listed PR's cells and return the summary."""
    out_dir = Path(out_dir)
    summary: dict[str, dict] = {}
    for pr, side, task, trial, path, row in iter_cells(out_dir):
        spec = patterns.get(pr)
        if spec is None:
            continue
        task_name = str(row.get("task") or task)
        files = transcript_files(out_dir, pr, side, task_name, trial, row)
        files.extend(evidence_files(out_dir, pr, side, task_name, trial))
        # A transcript path can also sit inside the evidence dir; search once.
        unique: list[Path] = []
        seen: set[Path] = set()
        for item in files:
            resolved = item.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            unique.append(item)
        status = classify_files(unique, spec.compiled)
        row["exercised"] = status
        publish_text(path, json.dumps(row, sort_keys=True))
        pr_summary = summary.setdefault(pr, {"task": spec.task, "sides": {}})
        side_summary = pr_summary["sides"].setdefault(side, _empty_counts())
        side_summary[status] += 1
    payload = {"prs": summary}
    publish_text(
        out_dir / "evidence-summary.json",
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
    )
    return payload


def render_summary(payload: dict) -> str:
    lines = ["pr side exercised not_exercised undeterminable"]
    prs = payload.get("prs") or {}
    for pr in sorted(prs):
        sides = prs[pr].get("sides") or {}
        if not sides:
            lines.append(f"{pr} - 0 0 0")
            continue
        for side in sorted(sides):
            counts = sides[side]
            lines.append(
                f"{pr} {side} {counts.get(EXERCISED, 0)} "
                f"{counts.get(NOT_EXERCISED, 0)} {counts.get(UNDETERMINABLE, 0)}"
            )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Grep A/B transcripts and copied OpenCode storage for each PR's evidence pattern",
    )
    parser.add_argument("out", type=Path, help="A/B output directory (results/ab)")
    parser.add_argument(
        "patterns",
        nargs="?",
        type=Path,
        default=DEFAULT_PATTERNS,
        help="CSV with pr,task,evidence_pattern (default: thesis/ab/fixtures/trigger-evidence.csv)",
    )
    args = parser.parse_args(argv)
    try:
        patterns = load_patterns(args.patterns)
        payload = annotate(args.out, patterns)
    except EvidenceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(render_summary(payload))
    print(args.out / "evidence-summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
