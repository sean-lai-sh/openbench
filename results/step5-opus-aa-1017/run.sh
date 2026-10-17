# Step 5 Opus 5.5 A/A, mirrors step 2 (results/aa-sonnet-1016/run.sh): --aa (parent build both sides), 30/side, --jobs 4,
# OpenCode 26821 trig-todo-task and Oh My Pi omp-36 trig-omp-reported (default thinking). Step 2 ran under `uv run`, so the venv is first on PATH here too.
# Added per PM: --order interleave-seeded --seed 1016 (first_side recorded per cell). One harness per invocation; authguard; cap = 800 - spend in other step5 dirs.
# usage: run.sh <oc|omp> <trials> <label>
while pgrep -f "thesis.ab.run_ab" >/dev/null; do sleep 30; done
export GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d VERTEX_LOCATION=global GOOGLE_APPLICATION_CREDENTIALS=/home/box/.config/gcloud/application_default_credentials.json PATH=/workspace/openbench-ab/.venv/bin:/home/box/google-cloud-sdk/bin:$PATH
PY=/workspace/openbench-ab/.venv/bin/python; RES=/workspace/openbench-ab/results; R=$RES/step5-opus-aa-1017; STOP=$R/QUEUE-STOP; WT=/tmp/ob-step4
H=$1; N=$2; LABEL=$3; OUT=$RES/step5-opus-aa-1017-$LABEL; mkdir -p $OUT; rm -f $STOP
if [ $H = oc ]; then A="$WT/thesis/ab/fixtures/opencode-harness-prs.csv --pr 26821 --task-map $WT/thesis/ab/fixtures/trigger-tasks.csv --cache $RES/opencode-src"
else A="$WT/thesis/ab/fixtures/pi-harness-prs.csv --pr omp-36 --tasks trig-omp-reported --cache $RES/omp-cache"; fi
C=$($PY - "$OUT" <<'PY'
import json,glob,sys
sys.path.insert(0,'/tmp/ob-step4')
from thesis.ab.summarize import row_cost
ex=sys.argv[1].rstrip('/')
ds=[d for d in glob.glob('/workspace/openbench-ab/results/step5-opus-aa-1017*') if d.rstrip('/')!=ex]
print(f"{800-sum((row_cost(json.load(open(p))) or 0) for d in ds for p in glob.glob(d+'/*/cells/*/*/*.json')):.2f}")
PY
)
echo "$(date '+%F %T %Z') start $LABEL $H trials=$N (wt $(git -C $WT rev-parse --short HEAD)) cap=$C free=$(df -BG --output=avail / | tail -1)" >> $R/driver.log
( cd $WT && exec setsid $PY -m thesis.ab.run_ab $A --aa --trials $N --jobs 4 --vertex-model claude-opus-5-5 --out $OUT --order interleave-seeded --seed 1016 --max-cost-usd $C > $OUT/$LABEL.log 2>&1 ) &
P=$!; sleep 2
$PY $R/authguard.py $OUT $(ps -o pgid= -p $P 2>/dev/null || echo $P) $STOP >> $OUT/$LABEL.guard.log 2>&1 &
wait $P; rc=$?
echo "$(date '+%F %T %Z') end $LABEL rc=$rc free=$(df -BG --output=avail / | tail -1)$([ -e $STOP ] && echo " STOPPED: $(cat $STOP)")" >> $R/driver.log
