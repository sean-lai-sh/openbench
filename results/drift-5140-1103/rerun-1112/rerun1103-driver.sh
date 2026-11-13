#!/bin/bash
# Rerun of the 9 skipped 11/03 slots (drift 5140). Same head/pin/image/cell.sh as the 11/12 run. Stop at $15.
set -u
R=$HOME/h2/drift-5140-1103; OB=$HOME/ob-d5140; N=d5140r-opus; STOPAT=15
IMAGE=h2-env:1022; DIG=sha256:<REDACTED_HEX>
CELLS=5140/with/dna-insert/1,5140/with/filter-js-from-html/1,5140/with/model-extraction-relu-logits/1,5140/with/polyglot-rust-c/1,5140/without/dna-insert/1,5140/without/filter-js-from-html/1,5140/without/model-extraction-relu-logits/1,5140/without/polyglot-rust-c/1,5140/without/regex-chess/1
log(){ echo "$(TZ=America/New_York date '+%F %T %Z') $*" | tee -a $R/rerun1103-driver.log; }
COMMIT=$(git -C $OB rev-parse HEAD)
[ "$COMMIT" = <REDACTED_HEX> ] || { log "REFUSE commit $COMMIT"; exit 8; }
[ -z "$(git -C $OB status --porcelain)" ] || { log "REFUSE dirty worktree"; exit 8; }
[ "$(sudo docker image inspect -f '{{.Id}}' $IMAGE)" = "$DIG" ] || { log "REFUSE image"; exit 8; }
python3 $OB/thesis/ab/h2env/spend_monitor.py --self-test >> $R/guard.log 2>&1 || { log "REFUSE self-test"; exit 8; }
cp -n $R/opus/run.log $R/opus/run-1112.log
BASE=$(python3 $OB/thesis/ab/h2env/pair_spend.py $R/opus | sed 's/total=\([0-9.]*\).*/\1/')
touch $R/.rerun1103-start
log "start rerun1103 code=$COMMIT image=$IMAGE@$DIG pin=2.0.50 stop_at=\$$STOPAT base=\$$BASE cells=$CELLS"
sudo docker run -d --name $N --network host -e OBENCH_INSTANCE_ID=8187537343833955709 -e OBENCH_RUNNER_COMMIT=$COMMIT -e OBENCH_ADC_METADATA=1 \
 -e GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d -e TZ=America/New_York -e OBENCH_CELL_IMAGE=$IMAGE@$DIG -e VERTEX_LOCATION=global \
 -e OBENCH_VM_TYPE=n2-standard-16 -e OBENCH_VM_NAME=<HOST> -v $OB:/ob -v $HOME/h1:/h1 -v $HOME/h2:/h2 $IMAGE \
 /h2/drift-5140-1103/cell.sh claude-opus-5-5 5140 2.0.50 /h2/drift-5140-1103/opus /h2/h2-hardsuite-1022/opus "$CELLS" >> $R/rerun1103-driver.log
est(){ sudo python3 - "$R" <<'P'
import json,sys,os
from pathlib import Path
R=Path(sys.argv[1]); t0=os.path.getmtime(R/'.rerun1103-start'); e=0.0
for p in (R/'opus/proxy-ledger').glob('*.jsonl'):
    if os.path.getmtime(p)<t0: continue
    for l in open(p):
        try: d=json.loads(l)
        except Exception: continue
        e+=d.get('input_uncached',0)*5e-6+d.get('output',0)*25e-6+d.get('cache_read',0)*0.5e-6+d.get('cache_write',0)*6.25e-6
print(f"{e:.4f}")
P
}
while sudo docker ps -q -f name="^$N$" | grep -q .; do
 C=$(python3 $OB/thesis/ab/h2env/pair_spend.py $R/opus); T=$(echo "$C" | sed 's/total=\([0-9.]*\).*/\1/'); D=$(python3 -c "print(f'{$T-$BASE:.4f}')"); E=$(est)
 echo "$(TZ=America/New_York date '+%F %T %Z') done_spend=\$$D ledger_est=\$$E $C" >> $R/rerun1103-spend.log
 if python3 -c "import sys;sys.exit(0 if max($D,$E)>=$STOPAT else 1)"; then log "STOP spend done=$D est=$E"; echo "STOP rerun1103 spend $D/$E" > $R/STOPPED.rerun1103; sudo docker stop -t 30 $N; fi
 sleep 30
done
sudo docker logs $N > $R/container-rerun1103.log 2>&1
C=$(python3 $OB/thesis/ab/h2env/pair_spend.py $R/opus); T=$(echo "$C" | sed 's/total=\([0-9.]*\).*/\1/')
log "end $N exit=$(sudo docker inspect -f '{{.State.ExitCode}}' $N) rerun_spend=\$$(python3 -c "print(f'{$T-$BASE:.4f}')") ledger_est=\$$(est) $C"
log "driver done $(cat $R/STOPPED.rerun1103 2>/dev/null)"
