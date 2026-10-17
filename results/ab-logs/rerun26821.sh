#!/bin/bash
cd /workspace/openbench-ab
while kill -0 1221467 2>/dev/null; do sleep 15; done
export GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d VERTEX_LOCATION=global GOOGLE_APPLICATION_CREDENTIALS=/home/box/.config/gcloud/application_default_credentials.json
echo "=== PR 26821 rerun start $(date -Is)"
python3 -m thesis.ab.run_ab thesis/ab/fixtures/opencode-harness-prs.csv --pr 26821 --trials 3 --jobs 8 --out results/ab --max-cost-usd 200 > results/ab-logs/pr-26821-rerun.log 2>&1
echo "=== PR 26821 rerun exit $? $(date -Is)"
