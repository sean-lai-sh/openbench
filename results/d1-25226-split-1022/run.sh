#!/bin/bash
# D1 25226 split. usage: run.sh <out> <label> <trials> <cap>. Runner /tmp/ob-25226-split-runner (12393ffd8, sparse), parallel with F02 (Sean waived one-at-a-time 2026-10-22).
export GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d VERTEX_LOCATION=global GOOGLE_APPLICATION_CREDENTIALS=/home/box/.config/gcloud/application_default_credentials.json PATH=/home/box/.dotnet:/home/box/google-cloud-sdk/bin:$PATH DOTNET_ROOT=/home/box/.dotnet
PY=/workspace/openbench-ab/.venv/bin/python; RES=/workspace/openbench-ab/results; WT=/tmp/ob-25226-split-runner; FX=$WT/thesis/ab/fixtures/d1-25226-split
OUT=$1; LABEL=$2; N=$3; CAP=$4; D=$RES/d1-25226-split-1022; mkdir -p $OUT
F=$(df -BG --output=avail / | tail -1 | tr -dc 0-9); [ $F -lt 12 ] && { echo "$(date '+%F %T %Z') $LABEL not started: free ${F}G<12G" >> $D/driver.log; exit 1; }
echo "$(date '+%F %T %Z') start $LABEL trials=$N cap=$CAP free=${F}G" >> $D/driver.log
( cd $WT && exec setsid $PY -m thesis.ab.run_ab $FX/prs.csv --pr 925226,825226 --task-map $FX/task-map.csv --trials $N --jobs 2 --vertex-model claude-sonnet-5-5 --out $OUT --cache $RES/opencode-src --order interleave-seeded --seed 1016 --max-cost-usd $CAP > $OUT/$LABEL.log 2>&1 ) &
P=$!; sleep 2; G=$(ps -o pgid= -p $P | tr -d ' '); G=${G:-$P}
$PY $RES/step6-opus-1017/authguard.py $OUT $G $D/STOP >> $OUT/$LABEL.guard.log 2>&1 &
( while kill -0 $P 2>/dev/null; do F=$(df -BG --output=avail / | tail -1 | tr -dc 0-9)
   echo "$(date '+%F %T %Z') free=${F}G box_cells=$(pgrep -fc 'opencode-src/bin/.*/opencode run') mine=$(pgrep -g $G -fc 'opencode run')" >> $OUT/$LABEL.concurrency.log
   if [ $F -lt 12 ]; then echo "disk ${F}G<12G during $LABEL" > $D/STOP; kill -TERM -$G; break; fi; sleep 20; done ) &
wait $P; echo "$(date '+%F %T %Z') end $LABEL rc=$? free=$(df -BG --output=avail / | tail -1)" >> $D/driver.log
