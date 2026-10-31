#!/bin/bash
# Researcher 13:49 EDT: pause 3052, start no new cells, let running cells finish. Freeze run_ab parent, then freeze each worker once it has no running cell.
L=$HOME/h2/env-rerun-1031c/pause.log; P=11126; W="11546 11876 11878 11880"
sudo kill -STOP $P; echo "$(date "+%F %T %Z") SIGSTOP parent $P" >> $L
declare -A done
while [ ${#done[@]} -lt 4 ]; do
 for w in $W; do [ -n "${done[$w]:-}" ] && continue
  if [ -z "$(pgrep -P $w)" ]; then sleep 1; if [ -z "$(pgrep -P $w)" ]; then sudo kill -STOP $w; done[$w]=1; echo "$(date "+%F %T %Z") worker $w idle -> SIGSTOP" >> $L; fi; fi
 done; sleep 1; done
echo "$(date "+%F %T %Z") all cells drained; paused" >> $L
