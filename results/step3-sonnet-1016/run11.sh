# After Sean's ADC re-login (2026-10-17 14:12 ET). One invocation at a time, seeded 1016, wt /tmp/ob-run.
# 1) auth smoke: 5066 --trials 1 -> step3-sonnet-1016-authsmoke; must have metered, non-auth cells.
# 2) 5066 30/side -> step3-sonnet-1016-reorder   3) 21070,22390,24974,25226,25431 -> make-rebuild2
# 4) 23771 with /home/box/.dotnet on PATH -> make-rebuild2.  authguard.py stops the whole queue on >3/10 auth fails or <5 GB free.
while pgrep -f "thesis.ab.run_ab.*step3-sonnet" >/dev/null; do sleep 30; done
export GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d VERTEX_LOCATION=global GOOGLE_APPLICATION_CREDENTIALS=/home/box/.config/gcloud/application_default_credentials.json PATH=/home/box/google-cloud-sdk/bin:$PATH
PY=/workspace/openbench-ab/.venv/bin/python; RES=/workspace/openbench-ab/results; R=$RES/step3-sonnet-1016; STOP=$R/QUEUE-STOP; rm -f $STOP
cap() { $PY - "$1" <<'PY'
import json,glob,sys
sys.path.insert(0,'/tmp/ob-run')
from thesis.ab.summarize import row_cost
ex=sys.argv[1].rstrip('/')
ds=[d for d in glob.glob('/workspace/openbench-ab/results/step3-sonnet-1016*') if d.rstrip('/')!=ex]
print(f"{1500-sum((row_cost(json.load(open(p))) or 0) for d in ds for p in glob.glob(d+'/*/cells/*/*/*.json')):.2f}")
PY
}
run() { # out label prs trials [extra PATH]
  local OUT=$1 LABEL=$2 PRS=$3 N=$4 XP=${5:-}; mkdir -p $OUT
  [ -e $STOP ] && { echo "$(date '+%F %T') skip $LABEL: $(cat $STOP)" >> $R/driver.log; return 1; }
  local C=$(cap $OUT)
  echo "$(date '+%F %T') start $LABEL $PRS trials=$N cap=$C ${XP:+PATH+=$XP}" >> $R/driver.log
  ( cd /tmp/ob-run && PATH=${XP:+$XP:}$PATH exec setsid $PY -m thesis.ab.run_ab /tmp/ob-run/thesis/ab/fixtures/opencode-harness-prs.csv --pr $PRS --task-map /tmp/ob-run/thesis/ab/fixtures/trigger-tasks.csv --trials $N --jobs 4 --vertex-model claude-sonnet-5-5 --out $OUT --cache $RES/opencode-src --order interleave-seeded --seed 1016 --max-cost-usd $C > $OUT/$LABEL.log 2>&1 ) &
  local P=$!; sleep 2
  $PY $R/authguard.py $OUT $(ps -o pgid= -p $P 2>/dev/null || echo $P) $STOP >> $OUT/$LABEL.guard.log 2>&1 &
  wait $P; local rc=$?
  echo "$(date '+%F %T') end $LABEL rc=$rc$([ -e $STOP ] && echo " STOPPED: $(cat $STOP)")" >> $R/driver.log
  [ -e $STOP ] && return 1 || return 0
}
echo "$(date '+%F %T') run11 start (post re-login: smoke, 5066, make-rebuild2)" >> $R/driver.log
run $RES/step3-sonnet-1016-authsmoke smoke5066 5066 1 || exit 1
$PY - <<'PY' || { echo "$(date '+%F %T') smoke FAILED (see authsmoke) - queue stopped" | tee -a $R/QUEUE-STOP >> $R/driver.log; exit 1; }
import json,glob,sys
rs=[json.load(open(p)) for p in glob.glob('/workspace/openbench-ab/results/step3-sonnet-1016-authsmoke/5066/cells/*/*/*.json')]
ok=[r for r in rs if r.get('failure_class') not in ('infra','incompatible') and (r.get('requests_output') or r.get('tokens_output'))]
print(len(rs),len(ok)); sys.exit(0 if rs and len(ok)==len(rs) else 1)
PY
echo "$(date '+%F %T') smoke ok" >> $R/driver.log
run $RES/step3-sonnet-1016-reorder rerun2c 5066 30 || exit 1
run $RES/step3-sonnet-1016-make-rebuild2 mr2a 21070,22390,24974,25226,25431 30 || exit 1
run $RES/step3-sonnet-1016-make-rebuild2 mr2b 23771 30 /home/box/.dotnet || exit 1
echo "$(date '+%F %T') run11 all done" >> $R/driver.log
