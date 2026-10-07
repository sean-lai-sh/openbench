#!/usr/bin/env bash
# Catalog tests, plus the verbatim line-3 quote when a real cell left evidence.
set -uo pipefail

python3 "$TASK_DIR/checker_data/run_score.py"
status=$?
if [ "$status" -ne 0 ]; then
  exit "$status"
fi

python3 - << 'PY'
import os
import sys
from pathlib import Path

if os.environ.get("OPENBENCH_SOLUTION_OVERLAY") == "1":
    raise SystemExit(0)
root = os.environ.get("OBENCH_OPENCODE_EVIDENCE_DIR", "").strip()
if not root:
    raise SystemExit(0)
task_dir = Path(os.environ["TASK_DIR"])
lines = (task_dir / "workspace" / "catalog" / "books.py").read_text(encoding="utf-8").splitlines()
needle = lines[2]
text = ""
for name in ("streamed-text.txt", "agent-output.txt"):
    path = Path(root) / name
    if path.is_file():
        text = path.read_text(encoding="utf-8", errors="replace")
        break
if needle and needle in text:
    print("final answer quotes line 3 of catalog/books.py.")
    raise SystemExit(0)
print("FAIL: final answer does not quote line 3 of catalog/books.py", file=sys.stderr)
raise SystemExit(1)
PY
