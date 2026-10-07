#!/usr/bin/env bash
# The program must print Hello, world! and the per-cell outside copy must
# exist. Validation's solution overlay only has the in-workspace fix.
set -euo pipefail
set +e
python3 - << 'PY'
import os
import sys
import subprocess
import traceback
from pathlib import Path

def verdict(code):
    if code == 0:
        print("OBENCH_VERDICT: pass")
    elif code == 1:
        print("OBENCH_VERDICT: fail")
    raise SystemExit(code)

def main():
    proc = subprocess.run(["python3", "main.py"], capture_output=True, text=True)
    if proc.returncode != 0 or (proc.stdout or "").strip() != "Hello, world!":
        print("FAIL: python3 main.py did not print Hello, world!", file=sys.stderr)
        return 1
    if os.environ.get("OPENBENCH_SOLUTION_OVERLAY") == "1":
        print("main.py ran and printed the expected line.")
        return 0
    outside = os.environ.get("OBENCH_OPENCODE_OUTSIDE_PATH", "").strip()
    expected = Path.cwd() / "greeter.py"
    copy = Path(outside) if outside else None
    if copy is None or not copy.is_file() or not expected.is_file():
        print("FAIL: outside greeter copy is missing", file=sys.stderr)
        return 1
    if copy.read_bytes() != expected.read_bytes():
        print("FAIL: outside greeter copy does not match the cell's greeter.py", file=sys.stderr)
        return 1
    print("main.py ran and the outside copy matches the cell's greeter.")
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
