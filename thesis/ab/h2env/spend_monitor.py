#!/usr/bin/env python3
"""Model-spend monitor for H2 gate/run drivers.

Sums ``requests_cost_usd`` over every cell record under ROOT, at any depth
(``.../cells/<side>/<task>/<trial>.json``). The old driver glob
``$R/*/*/cells/*/*/*.json`` missed cells one directory deeper and read $0.

Before a launch, run ``--self-test``: it reads a fixture with known nonzero
spend (the two #198 gate191-1030 cells, $0.3708) and exits nonzero if the
monitor reads 0 or the wrong total. A spend stop only counts after it passes.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent / "spend_fixture" / "gate191-1030"
FIXTURE_TOTAL_USD = 0.3708288


def cell_files(root) -> list[Path]:
    return sorted(
        p for p in Path(root).rglob("*.json")
        if "cells" in p.relative_to(root).parts[:-1]
    )


def total_cost(root) -> tuple[float, int]:
    total = 0.0
    files = cell_files(root)
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            total += float(data.get("requests_cost_usd") or 0)
    return total, len(files)


def self_test(fixture=FIXTURE, expect=FIXTURE_TOTAL_USD, tol=1e-6) -> tuple[bool, str]:
    total, n = total_cost(fixture)
    ok = n > 0 and total > 0 and abs(total - expect) <= tol
    return ok, f"spend self-test {'PASS' if ok else 'FAIL'}: {n} cells, ${total:.4f} (expect ${expect:.4f})"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", nargs="?")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--stop-at", type=float, default=None,
                    help="exit 10 when spend >= this many USD")
    args = ap.parse_args(argv)
    if args.self_test:
        ok, msg = self_test()
        print(msg)
        return 0 if ok else 3
    if not args.root:
        ap.error("ROOT is required unless --self-test")
    total, n = total_cost(args.root)
    print(f"spend={total:.4f} cells={n}")
    if args.stop_at is not None and total >= args.stop_at:
        return 10
    return 0


if __name__ == "__main__":
    sys.exit(main())
