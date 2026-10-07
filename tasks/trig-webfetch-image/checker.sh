#!/usr/bin/env bash
# Case-insensitive name from the cell seed. No seed means red, which is what
# the solution overlay writes for polarity validation.
set -euo pipefail
set +e
python3 - << 'PY'
import os
import sys
import traceback
from pathlib import Path

def verdict(code):
    if code == 0:
        print("OBENCH_VERDICT: pass")
    elif code == 1:
        print("OBENCH_VERDICT: fail")
    raise SystemExit(code)

def main():
    expected = os.environ.get("OBENCH_WEBFETCH_COLOUR", "red").strip().lower()
    try:
        text = Path("answer.txt").read_text(encoding="utf-8")
    except OSError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    got = text.strip().lower().strip(".")
    if got != expected:
        print(f"FAIL: {got!r} != {expected!r}", file=sys.stderr)
        return 1
    print(f"answer.txt names {expected}.")
    return 0

try:
    verdict(main())
except SystemExit:
    raise
except Exception:
    traceback.print_exc()
    raise SystemExit(2)
PY
status=$?
set -e
exit "$status"
