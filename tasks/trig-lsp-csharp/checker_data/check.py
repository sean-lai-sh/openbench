import shutil
import subprocess
import sys
from pathlib import Path

text = Path("Program.cs").read_text(encoding="utf-8")


def source_ok(body: str) -> bool:
    return "missingPort" not in body and "8417" in body


def pack_missing(output: str) -> bool:
    return any(code in output for code in ("NETSDK1045", "NETSDK1147", "NETSDK1047"))


dotnet = shutil.which("dotnet")
if dotnet:
    proc = subprocess.run(
        [dotnet, "build", "--nologo", "-v", "q"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    output = proc.stdout or ""
    if proc.returncode == 0:
        print("dotnet build passed")
        raise SystemExit(0)
    if not pack_missing(output):
        sys.stdout.write(output)
        raise SystemExit(proc.returncode)

if source_ok(text):
    print("Program.cs no longer references missingPort")
    raise SystemExit(0)
print("Program.cs still has the compile error", file=sys.stderr)
raise SystemExit(1)
