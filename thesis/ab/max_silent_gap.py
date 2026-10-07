"""Longest gap between consecutive OpenCode log lines in a finished A/B run.

Usage: ``python -m thesis.ab.max_silent_gap <results_dir>``

OpenCode logs look like ``INFO 2026-01-01T00:00:00 +15ms message``. The
``+Nms`` on a line is the gap since the previous log line, except the first
line in a file, whose delta is from logger startup. That first delta is
skipped. A later timestamped line with no ``+Nms`` uses the timestamp delta.
Each cell contributes its longest gap. Per side, the report prints the max
and the nearest-rank p99.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from datetime import datetime
from pathlib import Path

from thesis.ab.evidence import evidence_files, iter_cells, transcript_files

_LINE_RE = re.compile(
    r"(?m)^(?:DEBUG|INFO|WARN|ERROR)\s+"
    r"(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?)"
    r"(?:\s+\+(?P<ms>\d+)ms)?"
)


def _parse_ts(value: str) -> datetime | None:
    try:
        if "." in value:
            return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f")
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None


def longest_gap_s(text: str) -> float | None:
    """Longest gap in one log, in seconds. None when fewer than two lines match."""
    matches = list(_LINE_RE.finditer(text or ""))
    if len(matches) < 2:
        return None
    best = None
    prev_ts = _parse_ts(matches[0].group("ts"))
    for match in matches[1:]:
        gap = None
        ms = match.group("ms")
        if ms is not None:
            gap = int(ms) / 1000.0
        else:
            ts = _parse_ts(match.group("ts"))
            if prev_ts is not None and ts is not None:
                gap = (ts - prev_ts).total_seconds()
        ts = _parse_ts(match.group("ts"))
        if ts is not None:
            prev_ts = ts
        if gap is None or gap < 0:
            continue
        if best is None or gap > best:
            best = gap
    return best


def percentile_nearest(values: list[float], p: float = 0.99) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    index = min(n - 1, max(0, math.ceil(p * n) - 1))
    return ordered[index]


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _is_log(path: Path) -> bool:
    if path.suffix == ".log":
        return True
    return "log" in path.parts


def cell_sources(out_dir: Path, pr: str, side: str, task: str, trial: int, row: dict) -> list[str]:
    """Log files, else transcripts, else the cell's output tail."""
    logs = [
        path for path in evidence_files(out_dir, pr, side, task, trial)
        if _is_log(path)
    ]
    if logs:
        return [_read(path) for path in logs]
    transcripts = transcript_files(out_dir, pr, side, task, trial, row)
    if transcripts:
        return [_read(path) for path in transcripts]
    tail = row.get("output_tail")
    if isinstance(tail, str) and tail:
        return [tail]
    return []


def cell_gap(texts: list[str]) -> float | None:
    gaps = [gap for gap in (longest_gap_s(text) for text in texts) if gap is not None]
    if not gaps:
        return None
    return max(gaps)


def collect(out_dir: Path) -> list[dict]:
    rows = []
    for pr, side, task, trial, _path, row in iter_cells(out_dir):
        task_name = str(row.get("task") or task)
        gap = cell_gap(cell_sources(out_dir, pr, side, task_name, trial, row))
        rows.append({
            "pr": pr,
            "side": side,
            "task": task_name,
            "trial": trial,
            "gap_s": gap,
        })
    return rows


def side_summary(rows: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], list[float]] = {}
    order: list[tuple[str, str]] = []
    for row in rows:
        key = (row["pr"], row["side"])
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        if row["gap_s"] is not None:
            grouped[key].append(row["gap_s"])
    summary = []
    for pr, side in order:
        gaps = grouped[(pr, side)]
        summary.append({
            "pr": pr,
            "side": side,
            "n": len(gaps),
            "max": None if not gaps else max(gaps),
            "p99": percentile_nearest(gaps),
        })
    return summary


def render(out_dir: Path) -> str:
    rows = collect(out_dir)
    lines = []
    for row in rows:
        gap = row["gap_s"]
        shown = "none" if gap is None else f"{gap:.3f}"
        lines.append(
            f"{row['pr']} {row['side']} {row['task']} {row['trial']} gap={shown}"
        )
    lines.append("")
    for item in side_summary(rows):
        if item["n"] == 0:
            lines.append(f"{item['pr']} {item['side']} n=0 max= p99=")
            continue
        lines.append(
            f"{item['pr']} {item['side']} n={item['n']} "
            f"max={item['max']:.3f} p99={item['p99']:.3f}"
        )
    return "\n".join(lines) + ("\n" if lines else "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Longest silent gap between timestamped OpenCode log lines",
    )
    parser.add_argument("results_dir", type=Path)
    args = parser.parse_args(argv)
    sys.stdout.write(render(args.results_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
