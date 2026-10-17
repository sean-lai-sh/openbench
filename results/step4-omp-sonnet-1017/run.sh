# Step 4: Oh My Pi on Sonnet 5.5, screened rows (15 = every row with an OMP screen; 14 AWAITING-SCREEN rows are step 7; 20/22/45 not exercisable).
# Mirrors step-3 run12.sh. Runner worktree /tmp/ob-step4 = origin/main d7462cd (runner code = #69 232ed0f; #70-#75 are data-only).
# usage: run.sh <out> <label> <trials> <thinking default|off> <pr,pr,...>
# One invocation at a time; authguard stops on >3/10 auth fails or <5 GB free. run_ab's own PR early stop (>3 infra in first 10).
# Cap: --max-cost-usd = 1000 - ledger spend in every other step4-omp-sonnet-1017* dir; run_ab adds the spend already in --out (#69).
# 2026-10-17 16:30 EDT: .venv/bin added to PATH. Step 2 ran under `uv run`, which puts the venv first, so the checkers' `python3 -m pytest` found pytest; the 16:10 smoke ran without it (system python3 has no pytest) and every pytest-checked cell failed as wrong_answer. Smoke cells are kept as-is and labeled invalid in NOTES.md.
while pgrep -f "thesis.ab.run_ab" >/dev/null; do sleep 30; done
export GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d VERTEX_LOCATION=global GOOGLE_APPLICATION_CREDENTIALS=/home/box/.config/gcloud/application_default_credentials.json PATH=/workspace/openbench-ab/.venv/bin:/home/box/google-cloud-sdk/bin:$PATH
PY=/workspace/openbench-ab/.venv/bin/python; RES=/workspace/openbench-ab/results; R=$RES/step4-omp-sonnet-1017; STOP=$R/QUEUE-STOP; WT=/tmp/ob-step4
OUT=$1; LABEL=$2; N=$3; TH=$4; PRS=$5; mkdir -p $OUT; rm -f $STOP
C=$($PY - "$OUT" <<'PY'
import json,glob,sys
sys.path.insert(0,'/tmp/ob-step4')
from thesis.ab.summarize import row_cost
ex=sys.argv[1].rstrip('/')
ds=[d for d in glob.glob('/workspace/openbench-ab/results/step4-omp-sonnet-1017*') if d.rstrip('/')!=ex]
print(f"{1000-sum((row_cost(json.load(open(p))) or 0) for d in ds for p in glob.glob(d+'/*/cells/*/*/*.json')):.2f}")
PY
)
echo "$(date '+%F %T %Z') start $LABEL $PRS trials=$N thinking=$TH (wt $(git -C $WT rev-parse --short HEAD)) cap=$C free=$(df -BG --output=avail / | tail -1)" >> $R/driver.log
( cd $WT && exec setsid $PY -m thesis.ab.run_ab $WT/thesis/ab/fixtures/pi-harness-prs.csv --pr $PRS --task-map $R/omp-task-map.csv --trials $N --jobs 4 --vertex-model claude-sonnet-5-5 --omp-thinking $TH --out $OUT --cache $RES/omp-cache --order interleave-seeded --seed 1016 --max-cost-usd $C > $OUT/$LABEL.log 2>&1 ) &
P=$!; sleep 2
$PY $R/authguard.py $OUT $(ps -o pgid= -p $P 2>/dev/null || echo $P) $STOP >> $OUT/$LABEL.guard.log 2>&1 &
wait $P; rc=$?
echo "$(date '+%F %T %Z') end $LABEL rc=$rc free=$(df -BG --output=avail / | tail -1)$([ -e $STOP ] && echo " STOPPED: $(cat $STOP)")" >> $R/driver.log
