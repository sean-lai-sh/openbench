import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import verdict, run_hidden_tests, entry


def main():
    if not Path("weather.py").exists():
        return verdict(False, "weather.py missing")
    rc, out = run_hidden_tests()
    if rc != 0:
        return verdict(False, "hidden retry suite failed:\n" + out)
    return verdict(True, "retries 503 with bounded attempts; no retry on other errors")


if __name__ == "__main__":
    entry(main)
