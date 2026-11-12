#!/bin/bash
set -u
export OBENCH_HARBOR_APP_REWRITE=1
git config --global --add safe.directory '*'
[ -x /venv/bin/python ] || { python3 -m venv /venv && /venv/bin/pip install -q -e /ob; }
cd /ob
/venv/bin/python /o/config-check.py > /o/config-check.txt 2> /o/config-check.err
echo "config-check exit=$?" >> /o/config-check.err
common=(--task-map /o/task-map.csv --tasks-dir /ob/tasks --trials 30 --jobs 2
  --order interleave-seeded --seed 1016 --max-cost-usd 25 --cell-meta --cache /h1/opencode-src
  --timeout 2400 --timeout-cap-s 2400 --runner-commit "$OBENCH_RUNNER_COMMIT")
/venv/bin/python -m thesis.ab.run_ab /o/prs.csv --pr 725226 --model claude-sonnet-5-5 --vertex-model claude-sonnet-5-5 --dry-run "${common[@]}" --out /o > /o/dry-run.txt 2>&1
echo "exit=$?" >> /o/dry-run.txt
# Same run_ab call as the #253 smoke, launched through the observational body-capture wrapper.
PYTHONPATH=/ob /venv/bin/python /o/capture_run_ab.py /o/prs.csv --pr 725226 --model claude-sonnet-5-5 --vertex-model claude-sonnet-5-5 "${common[@]}" --out /o > /o/run.log 2>&1
echo "exit=$?" >> /o/run.log
/venv/bin/python /o/gate-check.py /o > /o/gate-check.txt 2> /o/gate-check.err
echo "gate-check exit=$?" >> /o/gate-check.err
touch /o/DONE
