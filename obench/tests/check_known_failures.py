"""Fail the merge on a test failure that is not in the known-failures baseline.

Usage:
    python3 -m unittest discover -s obench/tests -t . 2>&1 | tee suite.log
    python3 -m obench.tests.check_known_failures suite.log

Reads the unittest log's ``FAIL:`` / ``ERROR:`` headers and compares their test
ids with obench/tests/KNOWN_FAILURES.txt. Exits 1 if any failing id is not on
the list (a new failure), 0 otherwise. Ids on the list that now pass are
printed as "fixed" so the list can be trimmed; they do not fail the check.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

BASELINE = Path(__file__).with_name("KNOWN_FAILURES.txt")
HEADER = re.compile(r"^(?:FAIL|ERROR): (\S+) \(([^)]+)\)", re.M)


def failing_ids(log: str) -> set[str]:
    """Test ids from unittest's failure headers. Python >= 3.11 prints the full
    id in the parentheses; older ones print module.Class, so append the name."""
    out = set()
    for name, where in HEADER.findall(log):
        where = where.split(" ")[0]
        out.add(where if where.endswith("." + name) else f"{where}.{name}")
    return out


def known_ids(text: str) -> set[str]:
    return {l.split("#")[0].strip() for l in text.splitlines() if l.split("#")[0].strip()}


def check(log: str, baseline: str) -> tuple[set[str], set[str]]:
    failing, known = failing_ids(log), known_ids(baseline)
    return failing - known, known - failing


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    new, fixed = check(Path(argv[0]).read_text(errors="replace"), BASELINE.read_text())
    for t in sorted(fixed):
        print(f"fixed (drop from KNOWN_FAILURES.txt): {t}")
    for t in sorted(new):
        print(f"NEW FAILURE (not in KNOWN_FAILURES.txt): {t}")
    return 1 if new else 0


if __name__ == "__main__":
    sys.exit(main())
