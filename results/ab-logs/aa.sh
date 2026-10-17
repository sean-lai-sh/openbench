#!/bin/bash
cd /workspace/openbench-ab
while kill -0 1282750 2>/dev/null; do sleep 20; done
export GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d VERTEX_LOCATION=global GOOGLE_APPLICATION_CREDENTIALS=/home/box/.config/gcloud/application_default_credentials.json
spent=$(python3 results/ab-logs/p2stats.py total)
if python3 -c "import sys; sys.exit(0 if $spent + 40 > 850 else 1)"; then echo "AA SKIPPED: spend \$$spent near cap"; exit 0; fi
echo "AA START $(date -Is) spend=\$$spent"
setsid python3 -m thesis.ab.run_ab results/ab-logs/aa-17098.csv --pr 17098-aa --trials 3 --jobs 8 --out results/ab --cache /workspace/openbench-ab/results/opencode-src > results/ab-logs/aa-17098.log 2>&1 &
rp=$!
while kill -0 $rp 2>/dev/null; do sleep 30; s=$(python3 results/ab-logs/p2stats.py total); if python3 -c "import sys; sys.exit(0 if $s > 850 else 1)"; then echo "AA CAP HIT \$$s"; kill -- -$rp; break; fi; done
wait $rp; echo "AA END rc=$? $(date -Is) spend=\$(python3 results/ab-logs/p2stats.py total)"
python3 results/ab-logs/p2stats.py progress 17098-aa "A/A noise check"
