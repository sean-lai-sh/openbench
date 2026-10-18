# queue5: continue at C3 with runbatch3.sh (smoke-gate fix) after C2 + the 4204 make-up run. Same hold-for-data-PR behaviour.
R=/workspace/openbench-ab/results/step6-opus-1017
b() { local L=$1 P=$2; shift 2
  [ -e $R/QUEUE-STOP ] && { echo "$(date '+%F %T %Z') queue5 halted before $L: $(cat $R/QUEUE-STOP)" >> $R/driver.log; exit 1; }
  env "$@" bash $R/runbatch3.sh $L $P || exit 1
  touch $R/HOLD-$L; echo "$(date '+%F %T %Z') queue5 holding after $L for data PR" >> $R/driver.log
  while [ -e $R/HOLD-$L ]; do sleep 20; done; }
b C3 5140,6524,11731,12214,13090
b C4 13198,13269,17053,17098,19058
b C5 21070,22390,23771,25431
b C6 4838 OBENCH_THINKING_BLOCK_BINDING=drop_block
echo "$(date '+%F %T %Z') queue5 all done" >> $R/driver.log
