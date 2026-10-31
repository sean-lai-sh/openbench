#!/bin/bash
# Combined cross-VM spend stop: prior env spend $17.53 + run spend across 3 VMs; stop all at run >= $285 (cumulative ~$297 < $300).
L=/workspace/env1031b/central.log
while true; do
 T=0; LINE=""; ALIVE=0
 for v in thesis-h1-cpu:env-rerun-1031c thesis-h1-cpu-2:cells-rerun-1031b thesis-h1-cpu-3:cells-rerun-1031b; do
  n=${v%%:*}; o=${v#*:}
  out=$(/workspace/vm.sh $n "sudo python3 ~/h2/pairs1031.py ~/h2/$o | head -1; sudo docker ps -q -f name=e1031 | wc -l" 2>/dev/null | grep -E '^(total=|[0-9]+$)')
  c=$(echo "$out" | sed -n 's/^total=\([0-9.]*\).*/\1/p'); a=$(echo "$out" | grep -E '^[0-9]+$' | tail -1)
  T=$(python3 -c "print(round($T+${c:-0},4))"); ALIVE=$((ALIVE+${a:-0})); LINE="$LINE $n:\$${c:-?}/${a:-?}run"
 done
 echo "$(date '+%F %T %Z') run_total=\$$T cumulative=\$$(python3 -c "print(round($T+17.53,2))") live=$ALIVE$LINE" >> $L
 if python3 -c "import sys;sys.exit(0 if $T>=280 else 1)"; then echo "$(date) COMBINED STOP" >> $L
  for n in thesis-h1-cpu thesis-h1-cpu-2 thesis-h1-cpu-3; do /workspace/vm.sh $n 'sudo docker ps -q -f name=e1031 | xargs -r sudo docker stop -t 30' >> $L 2>&1; done; break; fi
 [ $ALIVE -eq 0 ] && { echo "$(date) all done" >> $L; break; }
 sleep 180
done
