import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import verdict, run_hidden_tests, entry


def main():
    try:
        compile(Path("handlers.py").read_text(encoding="utf-8"), "handlers.py", "exec")
    except (SyntaxError, FileNotFoundError) as e:
        return verdict(False, f"handlers.py does not compile: {e}")
    rc, out = run_hidden_tests()
    if rc != 0:
        return verdict(False, "hidden suite failed:\n" + out)
    return verdict(True, "all five handlers validate user_id; behaviour unchanged")


if __name__ == "__main__":
    entry(main)
