# After run6: 13331 merge side build timed out (bun script/build.ts: "TimeoutError: The operation timed out"), side marked incompatible.
# Fresh 30/side seeded run in a new dir so both sides share one launch. One invocation at a time.
while pgrep -f "step3-sonnet-1016/run6.sh" >/dev/null || pgrep -f "thesis.ab.run_ab.*step3-sonnet" >/dev/null; do sleep 30; done
export GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d VERTEX_LOCATION=global GOOGLE_APPLICATION_CREDENTIALS=/home/box/.config/gcloud/application_default_credentials.json PATH=/home/box/google-cloud-sdk/bin:$PATH
PY=/workspace/openbench-ab/.venv/bin/python; RES=/workspace/openbench-ab/results; R=$RES/step3-sonnet-1016; OUT=$RES/step3-sonnet-1016-13331-rebuild
mkdir -p $OUT
C=$($PY - <<'PY'
import json,glob,sys
sys.path.insert(0,'/tmp/ob-run')
from thesis.ab.summarize import row_cost
ds=[d for d in glob.glob('/workspace/openbench-ab/results/step3-sonnet-1016*') if not d.endswith('13331-rebuild')]
print(f"{1500-sum((row_cost(json.load(open(p))) or 0) for d in ds for p in glob.glob(d+'/*/cells/*/*/*.json')):.2f}")
PY
)
echo "$(date '+%F %T') start 13331 rebuild -> $OUT cap=$C" >> $R/driver.log
(cd /tmp/ob-run && $PY -m thesis.ab.run_ab /tmp/ob-run/thesis/ab/fixtures/opencode-harness-prs.csv --pr 13331 --task-map /tmp/ob-run/thesis/ab/fixtures/trigger-tasks.csv --trials 30 --jobs 4 --vertex-model claude-sonnet-5-5 --out $OUT --cache $RES/opencode-src --order interleave-seeded --seed 1016 --max-cost-usd $C > $OUT/run.log 2>&1); rc=$?
echo "$(date '+%F %T') end 13331 rebuild rc=$rc" >> $R/driver.log
