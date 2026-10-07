#!/usr/bin/env bash
# The three fee paths must resolve. A real cell must also name those files.
set -uo pipefail
python3 - << 'PY'
import os
import subprocess
import sys

def run(args):
    return subprocess.run(args, capture_output=True, text=True)

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
        raise SystemExit(1)
if os.environ.get("OPENBENCH_SOLUTION_OVERLAY") == "1":
    print("fee paths print the expected lines.")
    raise SystemExit(0)
root = os.environ.get("OBENCH_OPENCODE_EVIDENCE_DIR", "").strip()
final_path = os.environ.get("OBENCH_FINAL_ANSWER", "").strip()
if not root and not final_path:
    print("fee paths print the expected lines.")
    raise SystemExit(0)
from obench.final_answer import checker_text
text = checker_text()
needed = ("main.py", "billing/report.py", "billing/export/csv_writer.py")
missing = [item for item in needed if item not in text]
if missing:
    print("FAIL: final answer omits " + ", ".join(missing), file=sys.stderr)
    raise SystemExit(1)
print("fee paths work and the final answer lists every read site.")
raise SystemExit(0)
PY
