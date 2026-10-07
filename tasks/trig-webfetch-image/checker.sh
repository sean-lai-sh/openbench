#!/usr/bin/env bash
# Case-insensitive name from the cell seed. No seed means red, which is what
# the solution overlay writes for polarity validation.
set -uo pipefail
python3 - << 'PY'
import os
import sys
from pathlib import Path

expected = os.environ.get("OBENCH_WEBFETCH_COLOUR", "red").strip().lower()
try:
    text = Path("answer.txt").read_text(encoding="utf-8")
except OSError as exc:
    print(f"FAIL: {exc}", file=sys.stderr)
    raise SystemExit(1)
got = text.strip().lower().strip(".")
if got != expected:
    print(f"FAIL: {got!r} != {expected!r}", file=sys.stderr)
    raise SystemExit(1)
print(f"answer.txt names {expected}.")
PY
