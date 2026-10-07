#!/usr/bin/env bash
# Scores the add-feature task: fraction of (new @include feature tests +
# existing regression groups) passing. Prints a `SCORE: <0.0-1.0>` line and
# exits 0 only when every feature test passes and no regression group is
# broken. Runs with cwd = the agent's workspace copy; the scoring harness and
# its hidden tests live under $TASK_DIR/checker_data.
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
