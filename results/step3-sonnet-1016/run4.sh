cd /workspace/openbench-ab
export GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d VERTEX_LOCATION=global GOOGLE_APPLICATION_CREDENTIALS=/home/box/.config/gcloud/application_default_credentials.json PATH=/home/box/google-cloud-sdk/bin:$PATH
R=/workspace/openbench-ab/results/step3-sonnet-1016
RR=/workspace/openbench-ab/results/step3-sonnet-1016-reorder
# 1248 also ran in OLD ORDER: re-run it seeded into $RR after run3.sh (which re-runs 623,913,984) exits. One invocation at a time.
while pgrep -f "step3-sonnet-1016/run3.sh" >/dev/null || pgrep -f "thesis.ab.run_ab.*step3-sonnet" >/dev/null; do sleep 30; done
CAP=$(.venv/bin/python - <<'PY'
import json,glob,sys
sys.path.insert(0,'.')
from thesis.ab.summarize import row_cost
t=sum((row_cost(json.load(open(p))) or 0) for d in ("results/step3-sonnet-1016","results/step3-sonnet-1016-sidesorder-aborted","results/step3-sonnet-1016-oldorder-partial") for p in glob.glob(d+'/*/cells/*/*/*.json'))
print(f"{1500-t:.2f}")
PY
)
echo "$(date '+%F %T') start rerun 1248 -> $RR seed=1016 cap=$CAP" >> $R/driver.log
uv run python -m thesis.ab.run_ab thesis/ab/fixtures/opencode-harness-prs.csv --pr 1248 --task-map thesis/ab/fixtures/trigger-tasks.csv --trials 30 --jobs 4 --vertex-model claude-sonnet-5-5 --out $RR --cache /workspace/openbench-ab/results/opencode-src --order interleave-seeded --seed 1016 --max-cost-usd $CAP > $RR/rerun-1248.log 2>&1; rc=$?
echo "$(date '+%F %T') end rerun 1248 rc=$rc" >> $R/driver.log
