#!/usr/bin/env bash
# `python3 -m unittest` with no arguments does not discover tests/ (Python 3.12
# exits 5, "NO TESTS RAN"). Discover the file the instruction names.
set -euo pipefail
set +e
python3 -m unittest discover -s tests -p 'test_*.py'
status=$?
set -e
if [ "$status" -eq 0 ]; then
  printf '%s\n' "OBENCH_VERDICT: pass"
  exit 0
fi
if [ "$status" -eq 1 ]; then
  printf '%s\n' "OBENCH_VERDICT: fail"
  exit 1
fi
exit "$status"
