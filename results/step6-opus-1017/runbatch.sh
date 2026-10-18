#!/bin/bash
# Step-6 remainder: one batch = one run_ab invocation. usage: runbatch.sh <label> <pr,pr,...>   (env passthrough e.g. OBENCH_THINKING_BLOCK_BINDING=drop_block)
# 1) recreate each PR's OpenCode worktrees (mkworktrees.py) 2) smoke 1/side for the batch in step6-opus-1017-<label>-smoke
# 3) gate per PR: both cells metered, non-infra, upstream_model=claude-opus-5-5; auth-looking failure -> QUEUE-STOP; other failing PRs dropped and logged
# 4) 30/side for passing PRs in step6-opus-1017-<label>. Same flags as run.sh (#81 runner /tmp/ob-step4, interleave-seeded seed 1016, authguard, cap = 5000 - other step6 spend).
while pgrep -f "thesis.ab.run_ab" >/dev/null; do sleep 30; done
export GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d VERTEX_LOCATION=global GOOGLE_APPLICATION_CREDENTIALS=/home/box/.config/gcloud/application_default_credentials.json PATH=/home/box/.dotnet:/home/box/google-cloud-sdk/bin:$PATH DOTNET_ROOT=/home/box/.dotnet
PY=/workspace/openbench-ab/.venv/bin/python; RES=/workspace/openbench-ab/results; R=$RES/step6-opus-1017; STOP=$R/QUEUE-STOP; WT=/tmp/ob-step4; L=$1; PRS=$2
[ -e $STOP ] && { echo "$(date '+%F %T %Z') $L not started: $(cat $STOP)" >> $R/driver.log; exit 1; }
cap() { $PY - "$1" <<'PY'
import json,glob,sys
sys.path.insert(0,'/tmp/ob-step4')
from thesis.ab.summarize import row_cost
ex=sys.argv[1].rstrip('/')
ds=[d for d in glob.glob('/workspace/openbench-ab/results/step6-opus-1017*') if d.rstrip('/')!=ex]
print(f"{5000-sum((row_cost(json.load(open(p))) or 0) for d in ds for p in glob.glob(d+'/*/cells/*/*/*.json')):.2f}")
PY
}
run() { local OUT=$1 LABEL=$2 N=$3 P2=$4; mkdir -p $OUT; local C=$(cap $OUT)
  echo "$(date '+%F %T %Z') start $LABEL $P2 trials=$N (wt $(git -C $WT rev-parse --short HEAD)) cap=$C ${OBENCH_THINKING_BLOCK_BINDING:+OBENCH_THINKING_BLOCK_BINDING=$OBENCH_THINKING_BLOCK_BINDING }free=$(df -BG --output=avail / | tail -1)" >> $R/driver.log
  ( cd $WT && exec setsid $PY -m thesis.ab.run_ab $WT/thesis/ab/fixtures/opencode-harness-prs.csv --pr $P2 --task-map $WT/thesis/ab/fixtures/trigger-tasks.csv --trials $N --jobs 4 --vertex-model claude-opus-5-5 --out $OUT --cache $RES/opencode-src --order interleave-seeded --seed 1016 --max-cost-usd $C > $OUT/$LABEL.log 2>&1 ) &
  local P=$!; sleep 2
  $PY $R/authguard.py $OUT $(ps -o pgid= -p $P 2>/dev/null || echo $P) $STOP >> $OUT/$LABEL.guard.log 2>&1 &
  wait $P; local rc=$?
  echo "$(date '+%F %T %Z') end $LABEL rc=$rc free=$(df -BG --output=avail / | tail -1)$([ -e $STOP ] && echo " STOPPED: $(cat $STOP)")" >> $R/driver.log
  [ -e $STOP ] && return 1 || return 0
}
for p in ${PRS//,/ }; do $PY $R/mkworktrees.py $p 2>&1 | grep -E "^$p " >> $R/worktrees.txt; done
echo "$(date '+%F %T %Z') worktrees $L: $(for p in ${PRS//,/ }; do grep "^$p " $R/worktrees.txt | awk '{print $1":"$3" "$4}' | sort -u; done | tr '\n' ' ')" >> $R/driver.log
SM=$RES/step6-opus-1017-$L-smoke
run $SM smoke$L 1 $PRS || exit 1
OK=$($PY - $SM $PRS <<'PY'
import json,glob,sys
d,prs=sys.argv[1],sys.argv[2].split(','); ok=[]; AUTH=("ADC refresh failed","invalid authentication credentials","UNAUTHENTICATED","401")
for pr in prs:
    rs=[json.load(open(p)) for p in glob.glob(f'{d}/{pr}/cells/*/*/*.json')]
    good=[r for r in rs if r.get('failure_class') not in ('infra','incompatible','rate_limited','stalled') and (r.get('requests_output') or r.get('tokens_output')) and r.get('upstream_model')=='claude-opus-5-5']
    if len(rs)==2 and len(good)==2: ok.append(pr)
    else:
        s=json.dumps(rs); print(f"SMOKEFAIL {pr} cells={len(rs)} ok={len(good)} {[(r.get('failure_class'),r.get('upstream_model'),str(r.get('error') or r.get('failure_detail') or '')[:160]) for r in rs]}{' AUTH' if any(a in s for a in AUTH[:3]) else ''}",file=sys.stderr)
print(','.join(ok))
PY
2>>$R/driver.log)
if grep -q "SMOKEFAIL.*AUTH$" <(tail -10 $R/driver.log); then echo "$(date '+%F %T %Z') AUTH failure in smoke $L - STOP (no sign-in started)" | tee -a $STOP >> $R/driver.log; exit 1; fi
echo "$(date '+%F %T %Z') smoke $L gate: pass=[$OK] of [$PRS]" >> $R/driver.log
[ -z "$OK" ] && { echo "$(date '+%F %T %Z') smoke $L: no PR passed - STOP" | tee -a $STOP >> $R/driver.log; exit 1; }
run $RES/step6-opus-1017-$L full$L 30 $OK
echo "$(date '+%F %T %Z') batch $L done" >> $R/driver.log
