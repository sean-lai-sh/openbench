#!/bin/bash
# Binding combined $300 env stop, run from the box. Sums run spend on every VM:folder target plus PRIOR
# (cumulative env spend before these folders) and stops every VM's PFX containers at cumulative >= LIMIT.
# usage: PRIOR=17.53 [LIMIT=297] [PFX=e1031] env_rerun_central.sh LOG VM:folder...
LOG=$1; shift; PRIOR=${PRIOR:?}; LIMIT=${LIMIT:-297}; PFX=${PFX:-e1031}; VS=/workspace/vm.sh
while true; do
 T=0; LINE=""; ALIVE=0
 for v in "$@"; do n=${v%%:*}; o=${v#*:}
  out=$($VS $n "sudo python3 ~/wt-env1031b/thesis/ab/h2env/pair_spend.py ~/h2/$o 2>/dev/null || sudo python3 ~/h2/pairs1031.py ~/h2/$o; sudo docker ps -q -f name=$PFX | wc -l" 2>/dev/null | grep -E '^(total=|[0-9]+$)')
  c=$(echo "$out" | sed -n 's/^total=\([0-9.]*\).*/\1/p' | head -1); a=$(echo "$out" | grep -E '^[0-9]+$' | tail -1)
  T=$(python3 -c "print(round($T+${c:-0},4))"); ALIVE=$((ALIVE+${a:-0})); LINE="$LINE $n:$o=\$${c:-?}/${a:-?}"
 done
 CUM=$(python3 -c "print(round($T+$PRIOR,2))")
 echo "$(date '+%F %T %Z') run=\$$T cumulative=\$$CUM limit=\$$LIMIT live=$ALIVE$LINE" >> $LOG
 if python3 -c "import sys;sys.exit(0 if $CUM>=$LIMIT else 1)"; then echo "$(date '+%F %T %Z') COMBINED STOP" >> $LOG
  for v in "$@"; do $VS ${v%%:*} "sudo docker ps -q -f name=$PFX | xargs -r sudo docker stop -t 30" >> $LOG 2>&1; done; break; fi
 sleep 60
done
