"""Summarize a step-8 results directory from its saved ``complete.json``.

Completion is the file the launcher wrote (``step8_gate --complete``). This
module reads that file. It does not walk cell JSON or call ``complete()``
again. Off-route counts come from the saved ``route-scored.json``.

  python -m thesis.ab.step8_summarize RUN_DIR
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _off_route(run_dir: Path) -> int:
    path = run_dir / "route-scored.json"
    if not path.is_file():
        return 0
    off = _load(path).get("off_route") or {}
    if isinstance(off, dict):
        return sum(len(v) for v in off.values() if isinstance(v, list))
    if isinstance(off, list):
        return len(off)
    return 0


def summarize(run_dir: str | Path) -> dict:
    """Sides and scored cells listed in ``complete.json``.

    ``per_side`` is the number of scored cell paths under each ``pr/side``.
    ``complete`` is the ``complete`` object from the file, unchanged.
    """
    root = Path(run_dir)
    doc = _load(root / "complete.json")
    complete = doc.get("complete") or {}
    per_side = {}
    total = 0
    for key, side in complete.items():
        listed = side.get("cells") or []
        n = len(listed) if isinstance(listed, list) else 0
        per_side[key] = n
        total += n
    return {
        "sides": len(complete),
        "per_side": per_side,
        "scored_cells": total,
        "off_route": _off_route(root),
        "complete": complete,
    }


def _per_side_text(per_side: dict) -> str:
    counts = sorted(set(per_side.values()))
    if len(counts) == 1:
        return str(counts[0])
    return ",".join(f"{key}={n}" for key, n in sorted(per_side.items()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Summarize a step-8 results directory from complete.json",
    )
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args(argv)
    out = summarize(args.run_dir)
    print(
        f"sides {out['sides']} scored_cells_per_side {_per_side_text(out['per_side'])} "
        f"total {out['scored_cells']} off-route {out['off_route']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
