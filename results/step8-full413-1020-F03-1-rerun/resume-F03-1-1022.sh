#!/bin/bash
# 2026-10-22: F03-1 reruns (2986 + 6 never-run) into fresh dir; no chaining. QUEUE-STOP restored after.
S=/workspace/openbench-ab/results/step8-full413-1020; R=/workspace/openbench-ab/results
bash $S/run.sh $R/step8-full413-1020-F03-1-rerun F03-1-rerun 30 2986,3006,3079,3185,3192,3210,3225; rc=$?
if [ $rc -eq 0 ] && [ ! -e $S/QUEUE-STOP ]; then
  touch $S/DONE-F03-1; echo "$(date '+%F %T %Z') F03-1 complete (reruns in step8-full413-1020-F03-1-rerun)" >> $S/driver.log
  echo "F03-1 reruns done; awaiting Sean decision (VM move vs prune) before F03-2" > $S/QUEUE-STOP
fi
[ -e $S/QUEUE-STOP ] || echo "post-F03-1 hold" > $S/QUEUE-STOP
echo "$(date '+%F %T %Z') F03-1-rerun wrapper exit rc=$rc" >> $S/driver.log
