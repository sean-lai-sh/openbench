# Step-6 remainder queue: one batch at a time; stops at QUEUE-STOP. Each batch waits for any run_ab to exit. Commits are done by the agent between batches (queue pauses on HOLD-<label> until the agent removes it).
R=/workspace/openbench-ab/results/step6-opus-1017
b() { local L=$1 P=$2; shift 2
  [ -e $R/QUEUE-STOP ] && { echo "$(date '+%F %T %Z') queue3 halted before $L: $(cat $R/QUEUE-STOP)" >> $R/driver.log; exit 1; }
  env "$@" bash $R/runbatch.sh $L $P || exit 1
  touch $R/HOLD-$L; echo "$(date '+%F %T %Z') queue3 holding after $L for data PR" >> $R/driver.log
  while [ -e $R/HOLD-$L ]; do sleep 20; done; }
b C1 623,984,1248,2334,2367
b C2 3115,3369,4204,5066,5131
b C3 5140,6524,11731,12214,13090
b C4 13198,13269,17053,17098,19058
b C5 21070,22390,23771,25431
b C6 4838 OBENCH_THINKING_BLOCK_BINDING=drop_block
echo "$(date '+%F %T %Z') queue3 all done" >> $R/driver.log
