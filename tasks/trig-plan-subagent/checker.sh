#!/usr/bin/env bash
# Plan mode does not edit the workspace. A passing cell is either the
# overlaid fix (python3 main.py prints Total: 5.0) or a plan that stays in
# plan mode and names the misspelled settings key.
set -uo pipefail
python3 - << 'PY'
import os
import re
import subprocess
import sys
from pathlib import Path

proc = subprocess.run(["python3", "main.py"], capture_output=True, text=True)
if proc.returncode == 0 and (proc.stdout or "").strip() == "Total: 5.0":
    print("main.py ran and printed the expected line.")
    raise SystemExit(0)

root = os.environ.get("OBENCH_OPENCODE_EVIDENCE_DIR", "").strip()
chunks = []
if root and Path(root).is_dir():
    for path in Path(root).rglob("*"):
        if not path.is_file():
            continue
        try:
            if path.stat().st_size > 32 * 1024 * 1024:
                continue
            chunks.append(path.read_bytes().decode("latin-1"))
        except OSError:
            continue
text = "\n".join(chunks)
planned = (
    re.search(r'"mode"\s*:\s*"plan"', text) is not None
    and re.search(r"\brat\b", text) is not None
    and re.search(r"\brate\b", text) is not None
)
if planned:
    print("plan names the settings key and the cell stayed in plan mode.")
    raise SystemExit(0)
print("FAIL: neither the program nor a plan-mode fix was accepted", file=sys.stderr)
raise SystemExit(1)
PY
