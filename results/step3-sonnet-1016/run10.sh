# After run9: 21070 22390 23771 24974 25226 25431 both sides incompatible (bun install: tree-sitter-powershell node-gyp "not found: make"). Installed build-essential on the box 2026-10-17 ~04:30 EDT.
# Fresh 30/side seeded run of those 6 PRs in a new dir. One invocation at a time.
while pgrep -f "step3-sonnet-1016/run[6789].sh" >/dev/null || pgrep -f "thesis.ab.run_ab.*step3-sonnet" >/dev/null; do sleep 30; done
export GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d VERTEX_LOCATION=global GOOGLE_APPLICATION_CREDENTIALS=/home/box/.config/gcloud/application_default_credentials.json PATH=/home/box/google-cloud-sdk/bin:$PATH
PY=/workspace/openbench-ab/.venv/bin/python; RES=/workspace/openbench-ab/results; R=$RES/step3-sonnet-1016; OUT=$RES/step3-sonnet-1016-make-rebuild
mkdir -p $OUT
C=$($PY - <<'PY'
import json,glob,sys
sys.path.insert(0,'/tmp/ob-run')
from thesis.ab.summarize import row_cost
ds=[d for d in glob.glob('/workspace/openbench-ab/results/step3-sonnet-1016*') if not d.endswith('make-rebuild')]
print(f"{1500-sum((row_cost(json.load(open(p))) or 0) for d in ds for p in glob.glob(d+'/*/cells/*/*/*.json')):.2f}")
PY
)
echo "$(date '+%F %T') start make-rebuild 21070,22390,23771,24974,25226,25431 -> $OUT cap=$C" >> $R/driver.log
(cd /tmp/ob-run && $PY -m thesis.ab.run_ab /tmp/ob-run/thesis/ab/fixtures/opencode-harness-prs.csv --pr 21070,22390,23771,24974,25226,25431 --task-map /tmp/ob-run/thesis/ab/fixtures/trigger-tasks.csv --trials 30 --jobs 4 --vertex-model claude-sonnet-5-5 --out $OUT --cache $RES/opencode-src --order interleave-seeded --seed 1016 --max-cost-usd $C > $OUT/run.log 2>&1); rc=$?
echo "$(date '+%F %T') end make-rebuild 21070,22390,23771,24974,25226,25431 rc=$rc" >> $R/driver.log
