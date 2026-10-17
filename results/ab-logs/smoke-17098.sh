#!/bin/bash
set -u
cd /workspace/openbench-ab
export GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d
export VERTEX_LOCATION=global
export GOOGLE_APPLICATION_CREDENTIALS=/home/box/.config/gcloud/application_default_credentials.json
LOG=results/ab-logs/smoke-17098.run.log
echo "SMOKE START $(date -Is) HEAD=$(git rev-parse --short HEAD) spend=$(python3 results/ab-logs/p2stats.py total)" | tee "$LOG"
# default model-route=proxy
python3 -m thesis.ab.run_ab results/ab-logs/aa-17098.csv --pr 17098-aa --trials 3 --jobs 8 \
  --out results/ab --cache /workspace/openbench-ab/results/opencode-src \
  >> "$LOG" 2>&1
rc=$?
echo "SMOKE END rc=$rc $(date -Is) spend=$(python3 results/ab-logs/p2stats.py total)" | tee -a "$LOG"
exit $rc
