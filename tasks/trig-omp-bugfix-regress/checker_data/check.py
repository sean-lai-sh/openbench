import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import verdict, run_hidden_tests, entry


def main():
    rc, out = run_hidden_tests()
    if rc != 0:
        return verdict(False, "hidden suite failed:\n" + out)
    return verdict(True, "round_money rounds half up; other helpers intact")


if __name__ == "__main__":
    entry(main)
