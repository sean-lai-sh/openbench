#!/bin/bash
cd /workspace/openbench-ab
export GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d VERTEX_LOCATION=global GOOGLE_APPLICATION_CREDENTIALS=/home/box/.config/gcloud/application_default_credentials.json
echo "RESUME START $(date -Is)"
for pr in 26821 623; do
  echo "=== PR $pr resume start $(date -Is)"
  python3 -m thesis.ab.run_ab thesis/ab/fixtures/opencode-harness-prs.csv --pr $pr --trials 3 --jobs 8 --out results/ab --cache /workspace/openbench-ab/results/opencode-src --max-cost-usd 200 > results/ab-logs/pr-$pr-resume.log 2>&1
  echo "=== PR $pr resume exit $? $(date -Is)"
done
echo "RESUME END $(date -Is)"
