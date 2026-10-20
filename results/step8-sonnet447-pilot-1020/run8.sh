#!/bin/bash
# Step 8 pilot (447-PR Sonnet run, pilot only). usage: run8.sh <out> <label> <trials> <prs>
# OpenCode A/B on Sonnet 5.5, runner /tmp/ob-s6run (12393ffd8), --order interleave-seeded --seed 1016, absolute --out, authguard on.
# 2026-10-20 00:40 ET: .venv/bin removed from PATH (node-gyp used venv python3 without gyp -> bun install failed). Matches step-6 OpenCode runs.
# Cap: --max-cost-usd = 150 - ledger spend in every other step8-sonnet447-pilot-1020* dir (smoke included); run_ab adds spend already in --out.
while pgrep -f "thesis.ab.run_ab" >/dev/null; do sleep 30; done
export GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d VERTEX_LOCATION=global GOOGLE_APPLICATION_CREDENTIALS=/home/box/.config/gcloud/application_default_credentials.json PATH=/home/box/.dotnet:/home/box/google-cloud-sdk/bin:$PATH DOTNET_ROOT=/home/box/.dotnet
PY=/workspace/openbench-ab/.venv/bin/python; RES=/workspace/openbench-ab/results; R=$RES/step8-sonnet447-pilot-1020; STOP=$R/QUEUE-STOP; WT=/tmp/ob-s6run
OUT=$1; LABEL=$2; N=$3; PRS=$4; mkdir -p $OUT
[ -e $STOP ] && { echo "$(date '+%F %T %Z') $LABEL not started: $(cat $STOP)" >> $R/driver.log; exit 1; }
for p in ${PRS//,/ }; do $PY $R/mkworktrees.py $p 2>&1 | grep -E "^$p " >> $R/worktrees.txt; done
C=$($PY - "$OUT" <<'PY'
import json,glob,sys
sys.path.insert(0,'/tmp/ob-s6run')
from thesis.ab.summarize import row_cost
ex=sys.argv[1].rstrip('/')
ds=[d for d in glob.glob('/workspace/openbench-ab/results/step8-sonnet447-pilot-1020*') if d.rstrip('/')!=ex]
print(f"{150-sum((row_cost(json.load(open(p))) or 0) for d in ds for p in glob.glob(d+'/*/cells/*/*/*.json')):.2f}")
PY
)
echo "$(date '+%F %T %Z') start $LABEL $PRS trials=$N (wt $(git -C $WT rev-parse --short HEAD)) cap=$C free=$(df -BG --output=avail / | tail -1)" >> $R/driver.log
( cd $WT && exec setsid $PY -m thesis.ab.run_ab $R/pilot-prs.csv --pr $PRS --task-map $R/pilot-task-map.csv --trials $N --jobs 4 --vertex-model claude-sonnet-5-5 --out $OUT --cache $RES/opencode-src --order interleave-seeded --seed 1016 --max-cost-usd $C > $OUT/$LABEL.log 2>&1 ) &
P=$!; sleep 2
$PY $RES/step6-opus-1017/authguard.py $OUT $(ps -o pgid= -p $P 2>/dev/null || echo $P) $STOP >> $OUT/$LABEL.guard.log 2>&1 &
wait $P; rc=$?
echo "$(date '+%F %T %Z') end $LABEL rc=$rc free=$(df -BG --output=avail / | tail -1)$([ -e $STOP ] && echo " STOPPED: $(cat $STOP)")" >> $R/driver.log
