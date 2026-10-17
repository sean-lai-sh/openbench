#!/bin/bash
set -u
cd /workspace/openbench-ab
export GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d
export VERTEX_LOCATION=global
export GOOGLE_APPLICATION_CREDENTIALS=/home/box/.config/gcloud/application_default_credentials.json
LOG=results/ab-logs/smoke-4838.run.log
FIXTURE=thesis/ab/fixtures/opencode-harness-prs.csv
CACHE=/workspace/openbench-ab/results/opencode-src
echo "SMOKE4838 START $(date -Is) HEAD=$(git rev-parse --short HEAD) spend=$(python3 results/ab-logs/setaside_stats.py total)" | tee "$LOG"
python3 -m thesis.ab.run_ab "$FIXTURE" --pr 4838 --trials 3 --jobs 8 \
  --out results/ab --cache "$CACHE" \
  >> "$LOG" 2>&1
rc=$?
echo "SMOKE4838 END rc=$rc $(date -Is) spend=$(python3 results/ab-logs/setaside_stats.py total)" | tee -a "$LOG"
exit $rc
