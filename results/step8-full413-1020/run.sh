#!/bin/bash
# Step-8 full OpenCode Sonnet run (Sean OK 2026-10-20 12:04 ET). usage: run.sh <out> <label> <trials> <prs>
# Same settings as pilot run8.sh: runner /tmp/ob-s6run 12393ffd8, Sonnet 5.5, --order interleave-seeded --seed 1016, absolute --out, authguard; PATH without .venv/bin (node-gyp fix).
# Cap: --max-cost-usd = 5050 - spend in every other step8-full413-1020* dir. Disk watcher: free < 10 GB -> QUEUE-STOP + kill run (resume later).
while pgrep -f "thesis.ab.run_ab" >/dev/null; do sleep 30; done
export GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d VERTEX_LOCATION=global GOOGLE_APPLICATION_CREDENTIALS=/home/box/.config/gcloud/application_default_credentials.json PATH=/home/box/.dotnet:/home/box/google-cloud-sdk/bin:$PATH DOTNET_ROOT=/home/box/.dotnet
PY=/workspace/openbench-ab/.venv/bin/python; RES=/workspace/openbench-ab/results; R=$RES/step8-full413-1020; STOP=$R/QUEUE-STOP; WT=/tmp/ob-s6run
OUT=$1; LABEL=$2; N=$3; PRS=$4; mkdir -p $OUT
[ -e $STOP ] && { echo "$(date '+%F %T %Z') $LABEL not started: $(cat $STOP)" >> $R/driver.log; exit 1; }
F=$(df -BG --output=avail / | tail -1 | tr -dc 0-9); [ $F -lt 12 ] && { echo "disk: free ${F}G < 12G before $LABEL; paused" > $STOP; echo "$(date '+%F %T %Z') $LABEL paused: free ${F}G" >> $R/driver.log; exit 1; }
for p in ${PRS//,/ }; do $PY $R/mkworktrees.py $p 2>&1 | grep -E "^$p " >> $R/worktrees.txt; done
C=$($PY - "$OUT" <<'PY'
import json,glob,sys
sys.path.insert(0,'/tmp/ob-s6run')
from thesis.ab.summarize import row_cost
ex=sys.argv[1].rstrip('/')
ds=[d for d in glob.glob('/workspace/openbench-ab/results/step8-full413-1020*') if d.rstrip('/')!=ex]
print(f"{5050-sum((row_cost(json.load(open(p))) or 0) for d in ds for p in glob.glob(d+'/*/cells/*/*/*.json')):.2f}")
PY
)
echo "$(date '+%F %T %Z') start $LABEL $PRS trials=$N (wt $(git -C $WT rev-parse --short HEAD)) cap=$C free=$(df -BG --output=avail / | tail -1)" >> $R/driver.log
( cd $WT && exec setsid $PY -m thesis.ab.run_ab $R/prs.csv --pr $PRS --task-map $R/task-map.csv --trials $N --jobs 4 --vertex-model claude-sonnet-5-5 --out $OUT --cache $RES/opencode-src --order interleave-seeded --seed 1016 --max-cost-usd $C > $OUT/$LABEL.log 2>&1 ) &
P=$!; sleep 2; G=$(ps -o pgid= -p $P 2>/dev/null | tr -d ' '); G=${G:-$P}
$PY $RES/step6-opus-1017/authguard.py $OUT $G $STOP >> $OUT/$LABEL.guard.log 2>&1 &
( while kill -0 $P 2>/dev/null; do F=$(df -BG --output=avail / | tail -1 | tr -dc 0-9); if [ $F -lt 10 ]; then echo "disk: free ${F}G < 10G during $LABEL; run stopped" > $STOP; kill -TERM -$G; pkill -TERM -f "opencode-src/bin/.*/opencode run"; break; fi; sleep 30; done ) &
wait $P; rc=$?
echo "$(date '+%F %T %Z') end $LABEL rc=$rc free=$(df -BG --output=avail / | tail -1)$([ -e $STOP ] && echo " STOPPED: $(cat $STOP)")" >> $R/driver.log
