#!/usr/bin/env bash
# The three fee paths must resolve. A real cell must also name those files.
set -euo pipefail
set +e
python3 - << 'PY'
import os
import subprocess
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

def run(args):
    return subprocess.run(args, capture_output=True, text=True)

def main():
    checks = [
        (["python3", "main.py"], "Total: 5.0"),
        (["python3", "-m", "billing.report"], "Report fee: 0.5"),
        (["python3", "-m", "billing.export.csv_writer"], "CSV fee: 0.5"),
    ]
    for args, expected in checks:
        proc = run(args)
        got = (proc.stdout or "").strip()
        if proc.returncode != 0 or got != expected:
            print(f"FAIL: {' '.join(args)} did not print {expected!r}", file=sys.stderr)
            return 1
    if os.environ.get("OPENBENCH_SOLUTION_OVERLAY") == "1":
        print("fee paths print the expected lines.")
        return 0
    root = os.environ.get("OBENCH_OPENCODE_EVIDENCE_DIR", "").strip()
    final_path = os.environ.get("OBENCH_FINAL_ANSWER", "").strip()
    if not root and not final_path:
        print("fee paths print the expected lines.")
        return 0
    text = checker_text()
    needed = ("main.py", "billing/report.py", "billing/export/csv_writer.py")
    missing = [item for item in needed if item not in text]
    if missing:
        print("FAIL: final answer omits " + ", ".join(missing), file=sys.stderr)
        return 1
    print("fee paths work and the final answer lists every read site.")
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
