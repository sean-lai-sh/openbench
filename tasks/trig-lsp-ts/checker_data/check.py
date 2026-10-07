import shutil
import subprocess
import sys
import traceback
from pathlib import Path


def main() -> int:
    path = Path("src/index.ts")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        print("OBENCH_VERDICT: fail")
        return 1
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
        if proc.returncode == 0:
            print("OBENCH_VERDICT: pass")
            return 0
        if proc.returncode == 1:
            print("OBENCH_VERDICT: fail")
            return 1
        return proc.returncode or 2
    quoted = 'label:string="8417"' in compact or "label:string='8417'" in compact
    if "label:string=8417" in compact or not quoted:
        print("src/index.ts still assigns a number to a string", file=sys.stderr)
        print("OBENCH_VERDICT: fail")
        return 1
    print("src/index.ts assigns a string")
    print("OBENCH_VERDICT: pass")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        raise SystemExit(2)
