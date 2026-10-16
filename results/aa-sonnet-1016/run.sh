cd /workspace/openbench-ab
export GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d VERTEX_LOCATION=global GOOGLE_APPLICATION_CREDENTIALS=/home/box/.config/gcloud/application_default_credentials.json PATH=/home/box/google-cloud-sdk/bin:$PATH
R=/workspace/openbench-ab/results/aa-sonnet-1016
# Step 2 Sonnet A/A, runner 26286c3 (#35). Sequential: one invocation at a time. Cap $300 total; per-run guard $150.
uv run python -m thesis.ab.run_ab thesis/ab/fixtures/opencode-harness-prs.csv --pr 26821 --task-map thesis/ab/fixtures/trigger-tasks.csv --aa --trials 30 --jobs 4 --vertex-model claude-sonnet-5-5 --out $R/oc26821-aa --cache /workspace/openbench-ab/results/opencode-src --max-cost-usd 150 > $R/oc26821-aa.log 2>&1; echo oc rc=$?
uv run python -m thesis.ab.run_ab thesis/ab/fixtures/pi-harness-prs.csv --pr omp-36 --tasks trig-omp-reported --aa --trials 30 --jobs 4 --vertex-model claude-sonnet-5-5 --out $R/omp36-aa --cache /workspace/openbench-ab/results/omp-cache --max-cost-usd 150 > $R/omp36-aa.log 2>&1; echo omp rc=$?
