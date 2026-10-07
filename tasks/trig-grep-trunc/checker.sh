#!/usr/bin/env bash
set -euo pipefail
set +e
python3 "$TASK_DIR/checker_data/run_score.py"
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
