#!/bin/bash
cd /workspace/openbench-ab
export GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d VERTEX_LOCATION=global GOOGLE_APPLICATION_CREDENTIALS=/home/box/.config/gcloud/application_default_credentials.json
echo "START $(date -Is)"
for pr in 18140 26821 17098 623; do
  echo "=== PR $pr start $(date -Is)"
  python3 -m thesis.ab.run_ab thesis/ab/fixtures/opencode-harness-prs.csv --pr $pr --trials 3 --jobs 8 --out results/ab --max-cost-usd 200 > results/ab-logs/pr-$pr.log 2>&1
  echo "=== PR $pr exit $? $(date -Is)"
done
echo "END $(date -Is)"
