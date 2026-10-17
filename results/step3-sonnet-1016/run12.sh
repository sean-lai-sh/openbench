# 23771 after #69 (shared roslyn install, offline cert revocation). Worktree /tmp/ob-run-lsp = a34c5df + #69 cherry-pick,
# so the runner matches the rest of step 3 except for the LSP provisioning. /home/box/.dotnet on PATH.
# usage: run12.sh <out> <label> <trials>. One invocation at a time; authguard stops on >3/10 auth fails or <5 GB free.
# Cap: --max-cost-usd = 1500 - spend in every other step3-sonnet-1016* dir; run_ab adds the spend already in --out (#69 test).
while pgrep -f "thesis.ab.run_ab.*step3-sonnet" >/dev/null; do sleep 30; done
export GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d VERTEX_LOCATION=global GOOGLE_APPLICATION_CREDENTIALS=/home/box/.config/gcloud/application_default_credentials.json PATH=/home/box/.dotnet:/home/box/google-cloud-sdk/bin:$PATH DOTNET_ROOT=/home/box/.dotnet
PY=/workspace/openbench-ab/.venv/bin/python; RES=/workspace/openbench-ab/results; R=$RES/step3-sonnet-1016; STOP=$R/QUEUE-STOP; WT=/tmp/ob-run-lsp
OUT=$1; LABEL=$2; N=$3; mkdir -p $OUT; rm -f $STOP
C=$($PY - "$OUT" <<'PY'
import json,glob,sys
sys.path.insert(0,'/tmp/ob-run-lsp')
from thesis.ab.summarize import row_cost
ex=sys.argv[1].rstrip('/')
ds=[d for d in glob.glob('/workspace/openbench-ab/results/step3-sonnet-1016*') if d.rstrip('/')!=ex]
print(f"{1500-sum((row_cost(json.load(open(p))) or 0) for d in ds for p in glob.glob(d+'/*/cells/*/*/*.json')):.2f}")
PY
)
echo "$(date '+%F %T') start $LABEL 23771 trials=$N (wt $(git -C $WT rev-parse --short HEAD)) cap=$C PATH+=/home/box/.dotnet" >> $R/driver.log
( cd $WT && exec setsid $PY -m thesis.ab.run_ab $WT/thesis/ab/fixtures/opencode-harness-prs.csv --pr 23771 --task-map $WT/thesis/ab/fixtures/trigger-tasks.csv --trials $N --jobs 4 --vertex-model claude-sonnet-5-5 --out $OUT --cache $RES/opencode-src --order interleave-seeded --seed 1016 --max-cost-usd $C > $OUT/$LABEL.log 2>&1 ) &
P=$!; sleep 2
$PY $R/authguard.py $OUT $(ps -o pgid= -p $P 2>/dev/null || echo $P) $STOP >> $OUT/$LABEL.guard.log 2>&1 &
wait $P; rc=$?
echo "$(date '+%F %T') end $LABEL rc=$rc$([ -e $STOP ] && echo " STOPPED: $(cat $STOP)")" >> $R/driver.log
