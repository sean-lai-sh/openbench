# Resume after #49 (temperature strip + PR early stop). Runs from a separate worktree /tmp/ob-run (a34c5df), never checking out the live tree.
# One invocation at a time. Seeded order 1016. Cap $1.5K across all step3-sonnet-1016* dirs (each --max-cost-usd = 1500 - spend outside its --out).
export GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d VERTEX_LOCATION=global GOOGLE_APPLICATION_CREDENTIALS=/home/box/.config/gcloud/application_default_credentials.json PATH=/home/box/google-cloud-sdk/bin:$PATH
PY=/workspace/openbench-ab/.venv/bin/python
RES=/workspace/openbench-ab/results
R=$RES/step3-sonnet-1016; RR=$RES/step3-sonnet-1016-reorder; R38=$RES/step3-sonnet-1016-4838-dropblock
cap() { $PY - "$1" <<'PY'
import json,glob,sys
sys.path.insert(0,'/tmp/ob-run')
from thesis.ab.summarize import row_cost
ex=sys.argv[1].rstrip('/')
ds=[d for d in glob.glob('/workspace/openbench-ab/results/step3-sonnet-1016*') if d.rstrip('/')!=ex]
t=sum((row_cost(json.load(open(p))) or 0) for d in ds for p in glob.glob(d+'/*/cells/*/*/*.json'))
print(f"{1500-t:.2f}")
PY
}
run() { # dir label prs [env]
  local OUT=$1 LABEL=$2 PRS=$3 WT=${4:-/tmp/ob-run}
  local C=$(cap $OUT)
  echo "$(date '+%F %T') start $LABEL $PRS (wt $(git -C $WT rev-parse --short HEAD)) cap=$C" >> $R/driver.log
  (cd $WT && $PY -m thesis.ab.run_ab $WT/thesis/ab/fixtures/opencode-harness-prs.csv --pr $PRS --task-map $WT/thesis/ab/fixtures/trigger-tasks.csv --trials 30 --jobs 4 --vertex-model claude-sonnet-5-5 --out $OUT --cache $RES/opencode-src --order interleave-seeded --seed 1016 --max-cost-usd $C > $OUT/$LABEL.log 2>&1); local rc=$?
  echo "$(date '+%F %T') end $LABEL rc=$rc" >> $R/driver.log
}
echo "$(date '+%F %T') run6 start (after #49; 11731/12214/13090 temperature-400 cells moved to step3-sonnet-1016-tempfail)" >> $R/driver.log
run $R C1 11731,12214,13090,13198
run $R C2 13269,13331,17053,17098
run $R C3 19058,21070,22390,23771
run $R C4 24974,25226,25431,26821
mkdir -p $RR
run $RR rerun1 623,913,984,1248
run $RR rerun2 5066
mkdir -p $R38
OBENCH_THINKING_BLOCK_BINDING=drop_block run $R38 dropblock 4838 /tmp/ob-4838
echo "$(date '+%F %T') run6 all done" >> $R/driver.log
