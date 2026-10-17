cd /workspace/openbench-ab
export GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d VERTEX_LOCATION=global GOOGLE_APPLICATION_CREDENTIALS=/home/box/.config/gcloud/application_default_credentials.json PATH=/home/box/google-cloud-sdk/bin:$PATH
R=/workspace/openbench-ab/results/step3-sonnet-1016
RR=/workspace/openbench-ab/results/step3-sonnet-1016-reorder
R38=/workspace/openbench-ab/results/step3-sonnet-1016-4838-dropblock
# After run3 (main queue + 623/913/984 reruns) and run4 (1248 rerun): 5066 seeded rerun into $RR, then 4838 with draft #46 (drop_block) into $R38.
while pgrep -f "step3-sonnet-1016/run[34].sh" >/dev/null || pgrep -f "thesis.ab.run_ab.*step3-sonnet" >/dev/null; do sleep 30; done
cap() { .venv/bin/python - "$@" <<'PY'
import json,glob,sys
sys.path.insert(0,'.')
from thesis.ab.summarize import row_cost
ex=sys.argv[1]
ds=[d for d in glob.glob('results/step3-sonnet-1016*') if d.rstrip('/')!=ex]
t=sum((row_cost(json.load(open(p))) or 0) for d in ds for p in glob.glob(d+'/*/cells/*/*/*.json'))
print(f"{1500-t:.2f}")
PY
}
C=$(cap results/step3-sonnet-1016-reorder)
echo "$(date '+%F %T') start rerun 5066 -> $RR seed=1016 cap=$C" >> $R/driver.log
uv run python -m thesis.ab.run_ab thesis/ab/fixtures/opencode-harness-prs.csv --pr 5066 --task-map thesis/ab/fixtures/trigger-tasks.csv --trials 30 --jobs 4 --vertex-model claude-sonnet-5-5 --out $RR --cache /workspace/openbench-ab/results/opencode-src --order interleave-seeded --seed 1016 --max-cost-usd $C > $RR/rerun-5066.log 2>&1; rc=$?
echo "$(date '+%F %T') end rerun 5066 rc=$rc" >> $R/driver.log
mkdir -p $R38
C=$(cap results/step3-sonnet-1016-4838-dropblock)
echo "$(date '+%F %T') start 4838 drop_block (runner e11556f, draft #46) -> $R38 seed=1016 cap=$C" >> $R/driver.log
cd /tmp/ob-4838 && OBENCH_THINKING_BLOCK_BINDING=drop_block /workspace/openbench-ab/.venv/bin/python -m thesis.ab.run_ab thesis/ab/fixtures/opencode-harness-prs.csv --pr 4838 --task-map thesis/ab/fixtures/trigger-tasks.csv --trials 30 --jobs 4 --vertex-model claude-sonnet-5-5 --out $R38 --cache /workspace/openbench-ab/results/opencode-src --order interleave-seeded --seed 1016 --max-cost-usd $C > $R38/run.log 2>&1; rc=$?
echo "$(date '+%F %T') end 4838 drop_block rc=$rc" >> $R/driver.log
