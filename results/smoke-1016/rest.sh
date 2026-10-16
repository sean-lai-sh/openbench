cd /workspace/openbench-ab
export GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d VERTEX_LOCATION=global GOOGLE_APPLICATION_CREDENTIALS=/home/box/.config/gcloud/application_default_credentials.json PATH=/home/box/google-cloud-sdk/bin:$PATH
R=/workspace/openbench-ab/results/smoke-1016
uv run python -m thesis.ab.run_ab thesis/ab/fixtures/pi-harness-prs.csv --pr omp-36 --tasks trig-omp-reported --trials 1 --jobs 1 --vertex-model claude-opus-5-5 --out $R/omp36-opus --cache /workspace/openbench-ab/results/omp-cache --max-cost-usd 25 > $R/omp36-opus.log 2>&1; echo omp-opus rc=$?
for m in claude-sonnet-5-5 claude-opus-5-5; do
uv run python -m thesis.ab.run_ab thesis/ab/fixtures/opencode-harness-prs.csv --pr 26821 --task-map thesis/ab/fixtures/trigger-tasks.csv --trials 1 --jobs 1 --vertex-model $m --out $R/oc26821-${m#claude-} --cache /workspace/openbench-ab/results/opencode-src --max-cost-usd 25 > $R/oc26821-${m#claude-}.log 2>&1; echo oc $m rc=$?
done
