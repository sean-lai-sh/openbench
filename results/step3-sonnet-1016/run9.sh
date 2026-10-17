while pgrep -f "step3-sonnet-1016/run[678].sh" >/dev/null || pgrep -f "thesis.ab.run_ab.*step3-sonnet" >/dev/null; do sleep 30; done
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
echo "$(date '+%F %T') run9 start (resume rerun1 1248 + rerun2 5066 after unmetered-cell stop)" >> $R/driver.log
run $RR rerun1b 1248
run $RR rerun2b 5066
echo "$(date '+%F %T') run9 all done" >> $R/driver.log
