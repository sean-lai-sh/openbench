#!/bin/bash
set -u
export OBENCH_HARBOR_APP_REWRITE=1
git config --global --add safe.directory '*'
[ -x /venv/bin/python ] || { python3 -m venv /venv && /venv/bin/pip install -q -e /ob; }
cd /ob
common=(--task-map /o/A-model-vertex/task-map.csv --tasks-dir /ob/tasks --trials 1 --jobs 2
  --order interleave-seeded --seed 1016 --max-cost-usd 3 --cell-meta --cache /h1/opencode-src
  --timeout 2400 --timeout-cap-s 2400 --runner-commit "$OBENCH_RUNNER_COMMIT")
/venv/bin/python -m thesis.ab.run_ab /o/A-model-vertex/prs.csv --pr 725226 --model claude-sonnet-5-5 --vertex-model claude-sonnet-5-5 --dry-run "${common[@]}" --out /o/A-model-vertex > /o/A-model-vertex/dry-run.txt 2>&1; echo "exit=$?" >> /o/A-model-vertex/dry-run.txt
/venv/bin/python -m thesis.ab.run_ab /o/B-model-only/prs.csv --pr 725226 --model claude-sonnet-5-5 --dry-run "${common[@]}" --out /o/B-model-only > /o/B-model-only/dry-run.txt 2>&1; echo "exit=$?" >> /o/B-model-only/dry-run.txt
/venv/bin/python -m thesis.ab.run_ab /o/A-model-vertex/prs.csv --pr 725226 --model claude-sonnet-5-5 --vertex-model claude-sonnet-5-5 "${common[@]}" --out /o/A-model-vertex > /o/A-model-vertex/run.log 2>&1
a=$?; echo "exit=$a" >> /o/A-model-vertex/run.log
[ $a -eq 0 ] && { /venv/bin/python -m thesis.ab.run_ab /o/B-model-only/prs.csv --pr 725226 --model claude-sonnet-5-5 "${common[@]}" --out /o/B-model-only > /o/B-model-only/run.log 2>&1; echo "exit=$?" >> /o/B-model-only/run.log; }
touch /o/DONE
