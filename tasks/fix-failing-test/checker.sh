#!/usr/bin/env bash
# Runs with cwd set to a fresh copy of the task workspace.
# Exit 0 => task solved (all unit tests pass), nonzero => failed.
set -euo pipefail
set +e
python3 -m unittest -v
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
