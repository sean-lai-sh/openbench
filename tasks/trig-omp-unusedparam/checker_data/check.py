import subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import verdict, run_hidden_tests, entry, TASK_DIR


def main():
    p = subprocess.run([sys.executable, str(TASK_DIR / "checker_data" / "lint.py"), "."], capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        return verdict(False, "lint still failing:\n" + p.stdout[-2000:])
    rc, out = run_hidden_tests()
    if rc != 0:
        return verdict(False, "hidden suite failed:\n" + out)
    return verdict(True, "lint clean (checker's own linter) and tests pass")


if __name__ == "__main__":
    entry(main)
