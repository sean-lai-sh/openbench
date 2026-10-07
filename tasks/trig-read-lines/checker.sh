#!/usr/bin/env bash
# Catalog tests, plus the verbatim line-3 quote when a real cell left evidence.
set -euo pipefail

set +e
python3 "$TASK_DIR/checker_data/run_score.py"
status=$?
set -e
if [ "$status" -ne 0 ]; then
  if [ "$status" -eq 1 ]; then
    printf '%s\n' "OBENCH_VERDICT: fail"
  fi
  exit "$status"
fi

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

def checker_text():
    root = str(Path(os.environ["TASK_DIR"]).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    from obench.final_answer import checker_text as load
    return load()

def main():
    if os.environ.get("OPENBENCH_SOLUTION_OVERLAY") == "1":
        return 0
    root = os.environ.get("OBENCH_OPENCODE_EVIDENCE_DIR", "").strip()
    final_path = os.environ.get("OBENCH_FINAL_ANSWER", "").strip()
    if not root and not final_path:
        return 0
    task_dir = Path(os.environ["TASK_DIR"])
    lines = (task_dir / "workspace" / "catalog" / "members.py").read_text(encoding="utf-8").splitlines()
    needle = lines[2]
    text = checker_text()
    if needle and needle in text:
        print("final answer quotes line 3 of catalog/members.py.")
        return 0
    print("FAIL: final answer does not quote line 3 of catalog/members.py", file=sys.stderr)
    return 1

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
