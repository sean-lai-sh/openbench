# Step 7: OMP on Opus 5.5 (copied from step4 run.sh 2026-10-19; Opus, cap 600, step-7 CSV with row 24 fixture corrected).
# Mirrors step-3 run12.sh. Runner worktree /tmp/ob-step4 = origin/main d7462cd (runner code = #69 232ed0f; #70-#75 are data-only).
# 2026-10-17 18:35 EDT: runner worktree /tmp/ob-step4 moved to 12393ffd8 (#81: pi-natives sentinel fix for omp-44; the Opus strip is inert on Sonnet runs).
# BATCHCAP env (optional): per-batch cap = 1.2 x batch estimate; effective cap = min(600 - other spend, BATCHCAP).
# usage: run.sh <out> <label> <trials> <thinking default|off> <pr,pr,...>
# One invocation at a time; authguard stops on >3/10 auth fails or <5 GB free. run_ab's own PR early stop (>3 infra in first 10).
# Cap: --max-cost-usd = 600 - ledger spend in every other step7-opus-1019* dir; run_ab adds the spend already in --out (#69).
# 2026-10-17 16:30 EDT: .venv/bin added to PATH. Step 2 ran under `uv run`, which puts the venv first, so the checkers' `python3 -m pytest` found pytest; the 16:10 smoke ran without it (system python3 has no pytest) and every pytest-checked cell failed as wrong_answer. Smoke cells are kept as-is and labeled invalid in NOTES.md.
while pgrep -f "thesis.ab.run_ab" >/dev/null; do sleep 30; done
export GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d VERTEX_LOCATION=global GOOGLE_APPLICATION_CREDENTIALS=/home/box/.config/gcloud/application_default_credentials.json PATH=/workspace/openbench-ab/.venv/bin:/home/box/google-cloud-sdk/bin:$PATH
PY=/workspace/openbench-ab/.venv/bin/python; RES=/workspace/openbench-ab/results; R=$RES/step7-opus-1019; STOP=$R/QUEUE-STOP; WT=/tmp/ob-s6run
OUT=$1; LABEL=$2; N=$3; TH=$4; PRS=$5; mkdir -p $OUT; rm -f $STOP
C=$($PY - "$OUT" <<'PY'
import json,glob,sys
sys.path.insert(0,'/tmp/ob-s6run')
from thesis.ab.summarize import row_cost
ex=sys.argv[1].rstrip('/')
ds=[d for d in glob.glob('/workspace/openbench-ab/results/step7-opus-1019*') if d.rstrip('/')!=ex]
print(f"{600-sum((row_cost(json.load(open(p))) or 0) for d in ds for p in glob.glob(d+'/*/cells/*/*/*.json')):.2f}")
PY
)
[ -n "${BATCHCAP:-}" ] && C=$(python3 -c "print(f'{min($C,$BATCHCAP):.2f}')")
echo "$(date '+%F %T %Z') start $LABEL $PRS trials=$N thinking=$TH (wt $(git -C $WT rev-parse --short HEAD)) cap=$C free=$(df -BG --output=avail / | tail -1)" >> $R/driver.log
( cd $WT && exec setsid $PY -m thesis.ab.run_ab $R/pi-harness-prs-step7.csv --pr $PRS --task-map $R/omp-task-map.csv --trials $N --jobs 4 --vertex-model claude-opus-5-5 --omp-thinking $TH --out $OUT --cache $RES/omp-cache --order interleave-seeded --seed 1016 --max-cost-usd $C > $OUT/$LABEL.log 2>&1 ) &
P=$!; sleep 2
$PY $RES/step4-omp-sonnet-1017/authguard.py $OUT $(ps -o pgid= -p $P 2>/dev/null || echo $P) $STOP >> $OUT/$LABEL.guard.log 2>&1 &
wait $P; rc=$?
echo "$(date '+%F %T %Z') end $LABEL rc=$rc free=$(df -BG --output=avail / | tail -1)$([ -e $STOP ] && echo " STOPPED: $(cat $STOP)")" >> $R/driver.log
