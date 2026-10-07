import shutil
import subprocess
import sys
from pathlib import Path

text = Path("src/index.ts").read_text(encoding="utf-8")
compact = "".join(text.split())
tsc = Path("node_modules/typescript/lib/tsc.js")
if tsc.is_file() and shutil.which("node"):
    proc = subprocess.run(
        ["node", "node_modules/typescript/bin/tsc", "--noEmit"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    sys.stdout.write(proc.stdout or "")
    raise SystemExit(proc.returncode)
quoted = 'label:string="8417"' in compact or "label:string='8417'" in compact
if "label:string=8417" in compact or not quoted:
    print("src/index.ts still assigns a number to a string", file=sys.stderr)
    raise SystemExit(1)
print("src/index.ts assigns a string")
