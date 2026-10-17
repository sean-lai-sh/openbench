# Step 6 pulled forward (PM/Sean 2026-10-17 "Rerun the missing PR"): OpenCode on Opus 5.5, 30/side, ONE PR per invocation.
# PRs 913, 3052, 26821 (tasks as step3-sonnet-1016), 13331 (as -13331-rebuild), 24974, 25226 (as -make-rebuild2); all from fixtures/trigger-tasks.csv.
# Mirrors step-3 run11/run12 env (no venv on PATH, like step 3), runner /tmp/ob-step4 = origin/main (#69 runner code).
# --vertex-model claude-opus-5-5 (proxy MODEL_ID default; summarize.py prices it at Opus RATES).
# usage: run.sh <PR>   -> smoke 1/side in results/step6-opus-1017-<PR>-smoke; gate: every smoke cell metered, non-infra, upstream_model=claude-opus-5-5;
#                         then 30/side in results/step6-opus-1017-<PR>.
# Cap: --max-cost-usd = 5000 - ledger spend in every other step6-opus-1017* dir (step 4 tracked separately).
while pgrep -f "thesis.ab.run_ab" >/dev/null; do sleep 30; done
export GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d VERTEX_LOCATION=global GOOGLE_APPLICATION_CREDENTIALS=/home/box/.config/gcloud/application_default_credentials.json PATH=/home/box/.dotnet:/home/box/google-cloud-sdk/bin:$PATH DOTNET_ROOT=/home/box/.dotnet
PY=/workspace/openbench-ab/.venv/bin/python; RES=/workspace/openbench-ab/results; R=$RES/step6-opus-1017; STOP=$R/QUEUE-STOP; WT=/tmp/ob-step4; PR=$1
cap() { $PY - "$1" <<'PY'
import json,glob,sys
sys.path.insert(0,'/tmp/ob-step4')
from thesis.ab.summarize import row_cost
ex=sys.argv[1].rstrip('/')
ds=[d for d in glob.glob('/workspace/openbench-ab/results/step6-opus-1017*') if d.rstrip('/')!=ex]
print(f"{5000-sum((row_cost(json.load(open(p))) or 0) for d in ds for p in glob.glob(d+'/*/cells/*/*/*.json')):.2f}")
PY
}
run() { local OUT=$1 LABEL=$2 N=$3; mkdir -p $OUT
  [ -e $STOP ] && { echo "$(date '+%F %T %Z') skip $LABEL: $(cat $STOP)" >> $R/driver.log; return 1; }
  local C=$(cap $OUT)
  echo "$(date '+%F %T %Z') start $LABEL $PR trials=$N (wt $(git -C $WT rev-parse --short HEAD)) cap=$C free=$(df -BG --output=avail / | tail -1)" >> $R/driver.log
  ( cd $WT && exec setsid $PY -m thesis.ab.run_ab $WT/thesis/ab/fixtures/opencode-harness-prs.csv --pr $PR --task-map $WT/thesis/ab/fixtures/trigger-tasks.csv --trials $N --jobs 4 --vertex-model claude-opus-5-5 --out $OUT --cache $RES/opencode-src --order interleave-seeded --seed 1016 --max-cost-usd $C > $OUT/$LABEL.log 2>&1 ) &
  local P=$!; sleep 2
  $PY $R/authguard.py $OUT $(ps -o pgid= -p $P 2>/dev/null || echo $P) $STOP >> $OUT/$LABEL.guard.log 2>&1 &
  wait $P; local rc=$?
  echo "$(date '+%F %T %Z') end $LABEL rc=$rc free=$(df -BG --output=avail / | tail -1)$([ -e $STOP ] && echo " STOPPED: $(cat $STOP)")" >> $R/driver.log
  [ -e $STOP ] && return 1 || return 0
}
rm -f $STOP
run $RES/step6-opus-1017-$PR-smoke smoke$PR 1 || exit 1
$PY - $RES/step6-opus-1017-$PR-smoke $PR <<'PY' || { echo "$(date '+%F %T %Z') smoke $PR FAILED gate - queue stopped" | tee -a $STOP >> $R/driver.log; exit 1; }
import json,glob,sys
rs=[json.load(open(p)) for p in glob.glob(f'{sys.argv[1]}/{sys.argv[2]}/cells/*/*/*.json')]
ok=[r for r in rs if r.get('failure_class') not in ('infra','incompatible','rate_limited','stalled') and (r.get('requests_output') or r.get('tokens_output')) and r.get('upstream_model')=='claude-opus-5-5']
print(len(rs),len(ok),[(r.get('failure_class'),r.get('upstream_model')) for r in rs]); sys.exit(0 if len(rs)==2 and len(ok)==2 else 1)
PY
echo "$(date '+%F %T %Z') smoke $PR ok (upstream_model claude-opus-5-5 both sides)" >> $R/driver.log
run $RES/step6-opus-1017-$PR full$PR 30
