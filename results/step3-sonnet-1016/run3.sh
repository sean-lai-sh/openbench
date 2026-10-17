cd /workspace/openbench-ab
export GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d VERTEX_LOCATION=global GOOGLE_APPLICATION_CREDENTIALS=/home/box/.config/gcloud/application_default_credentials.json PATH=/home/box/google-cloud-sdk/bin:$PATH
R=/workspace/openbench-ab/results/step3-sonnet-1016
RR=/workspace/openbench-ab/results/step3-sonnet-1016-reorder
SEED=1016
# OLD ORDER: 623, 913, 984, 1248 ran on 9439542 with --order interleave (without first in every trial block).
# NEW ORDER: from 2334 on, runner 55b709a (#39 + #41 CLI seed fix), --order interleave-seeded --seed 1016 (per-PR seeded first side).
# Cap $1.5K across all step-3 dirs: --max-cost-usd only sees its own --out, so each invocation gets 1500 minus spend elsewhere.
git checkout -q --detach 55b709a
spent_other() { .venv/bin/python - "$@" <<'PY'
import json,glob,sys
sys.path.insert(0,'.')
from thesis.ab.summarize import row_cost
t=0
for d in sys.argv[1:]:
    for p in glob.glob(d+'/*/cells/*/*/*.json'):
        try: t+=row_cost(json.load(open(p))) or 0
        except Exception: pass
print(f"{1500-t:.2f}")
PY
}
OTHER="results/step3-sonnet-1016-sidesorder-aborted results/step3-sonnet-1016-oldorder-partial"
B1b=2334,2367,3052,3115
B2=3369,4204,4838,5066,5131,5140,6524,11731
B3=12214,13090,13198,13269,13331,17053,17098,19058
B4=21070,22390,23771,24974,25226,25431,26821
for b in B1b B2 B3 B4; do
  CAP=$(spent_other $OTHER $RR)
  echo "$(date '+%F %T') start $b ${!b} seed=$SEED cap=$CAP" >> $R/driver.log
  uv run python -m thesis.ab.run_ab thesis/ab/fixtures/opencode-harness-prs.csv --pr ${!b} --task-map thesis/ab/fixtures/trigger-tasks.csv --trials 30 --jobs 4 --vertex-model claude-sonnet-5-5 --out $R --cache /workspace/openbench-ab/results/opencode-src --order interleave-seeded --seed $SEED --max-cost-usd $CAP > $R/$b.log 2>&1; rc=$?
  echo "$(date '+%F %T') end $b rc=$rc" >> $R/driver.log
done
mkdir -p $RR
CAP=$(spent_other $OTHER $R)
echo "$(date '+%F %T') start rerun 623,913,984 -> $RR seed=$SEED cap=$CAP" >> $R/driver.log
uv run python -m thesis.ab.run_ab thesis/ab/fixtures/opencode-harness-prs.csv --pr 623,913,984 --task-map thesis/ab/fixtures/trigger-tasks.csv --trials 30 --jobs 4 --vertex-model claude-sonnet-5-5 --out $RR --cache /workspace/openbench-ab/results/opencode-src --order interleave-seeded --seed $SEED --max-cost-usd $CAP > $RR/rerun.log 2>&1; rc=$?
echo "$(date '+%F %T') end rerun rc=$rc" >> $R/driver.log
echo "$(date '+%F %T') all done" >> $R/driver.log
