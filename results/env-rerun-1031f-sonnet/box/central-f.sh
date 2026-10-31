#!/bin/bash
# Combined $297 env stop (box). v2 2026-10-31: polls only RUNNING VMs (one gcloud list per loop), short ssh timeout,
# keeps last-read spend for a VM that stopped (FROZEN) instead of counting it $0, flags never-read targets.
# usage: PRIOR=<cum env spend before these folders> [LIMIT=297] [PFX=e1031] central-f.sh LOG VM:folder...
LOG=$1; shift; PRIOR=${PRIOR:?}; LIMIT=${LIMIT:-297}; PFX=${PFX:-e1031}; declare -A LAST
while true; do
 RUN=" $(timeout 40 gcloud compute instances list --filter='status=RUNNING' --format='value(name)' 2>/dev/null | tr '\n' ' ') "
 T=0; LINE=""; ALIVE=0; UNREAD=0
 for v in "$@"; do n=${v%%:*}; o=${v#*:}; c=""; a=""
  if [[ "$RUN" == *" $n "* ]]; then
   out=$(timeout 60 gcloud compute ssh "$n" --zone us-central1-a --tunnel-through-iap --ssh-flag="-o ConnectTimeout=15" \
     --command "sudo python3 ~/h2/pairs1031.py ~/h2/$o | head -1; sudo docker ps -q -f name=$PFX | wc -l" 2>/dev/null | grep -E '^(total=|[0-9]+$)')
   c=$(echo "$out" | sed -n 's/^total=\([0-9.]*\).*/\1/p' | head -1); a=$(echo "$out" | grep -E '^[0-9]+$' | tail -1)
  fi
  if [ -n "$c" ]; then LAST[$v]=$c; st=live; elif [ -n "${LAST[$v]}" ]; then c=${LAST[$v]}; st=FROZEN; else c=0; st=UNREAD; UNREAD=1; fi
  T=$(python3 -c "print(round($T+$c,4))"); ALIVE=$((ALIVE+${a:-0})); LINE="$LINE $n:$o=\$$c/${a:-0}($st)"
 done
 CUM=$(python3 -c "print(round($T+$PRIOR,2))")
 echo "$(date '+%F %T %Z') run=\$$T cumulative=\$$CUM limit=\$$LIMIT live=$ALIVE unread=$UNREAD running=[${RUN// /,}]$LINE" >> $LOG
 if python3 -c "import sys;sys.exit(0 if $CUM>=$LIMIT else 1)"; then echo "$(date '+%F %T %Z') COMBINED STOP" >> $LOG
  for v in "$@"; do timeout 90 gcloud compute ssh ${v%%:*} --zone us-central1-a --tunnel-through-iap --ssh-flag="-o ConnectTimeout=15" --command "sudo docker ps -q -f name=$PFX | xargs -r sudo docker stop -t 30" >> $LOG 2>&1; done; break; fi
 sleep 60
done
