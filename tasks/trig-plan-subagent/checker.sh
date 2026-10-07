#!/usr/bin/env bash
# A live cell passes when the final answer names both rat and rate and the
# workspace is still the pristine tree. The golden solution overlay is the
# settings fix, which makes python3 main.py print Total: 5.0.
set -uo pipefail
python3 - << 'PY'
import os
import re
import subprocess
import sys
from pathlib import Path

def program_ok():
    proc = subprocess.run(["python3", "main.py"], capture_output=True, text=True)
    return proc.returncode == 0 and (proc.stdout or "").strip() == "Total: 5.0"

if os.environ.get("OPENBENCH_SOLUTION_OVERLAY") == "1":
    if program_ok():
        print("main.py ran and printed the expected line.")
        raise SystemExit(0)
    print("FAIL: solution overlay did not print Total: 5.0", file=sys.stderr)
    raise SystemExit(1)

def snapshot(root):
    found = {}
    base = Path(root)
    if not base.is_dir():
        return found
    for path in base.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        found[path.relative_to(base).as_posix()] = path.read_bytes()
    return found

task_dir = os.environ.get("TASK_DIR", "")
unchanged = bool(task_dir) and snapshot(Path(task_dir) / "workspace") == snapshot(Path.cwd())
from obench.final_answer import checker_text
text = checker_text()
names_both = re.search(r"\brat\b", text) is not None and re.search(r"\brate\b", text) is not None
if unchanged and names_both:
    print("final answer names rat and rate and the workspace is unchanged.")
    raise SystemExit(0)
print("FAIL: final answer must name rat and rate with no file modified", file=sys.stderr)
raise SystemExit(1)
PY
