# queue7: C6 = 4838 with OBENCH_THINKING_BLOCK_BINDING=drop_block (PM + Sean go, 2026-10-19 16:07 ET). runbatch3.sh, same settings. Sets HOLD-C6 at the end.
R=/workspace/openbench-ab/results/step6-opus-1017
[ -e $R/QUEUE-STOP ] && { echo "$(date '+%F %T %Z') queue7 halted: $(cat $R/QUEUE-STOP)" >> $R/driver.log; exit 1; }
env OBENCH_THINKING_BLOCK_BINDING=drop_block bash $R/runbatch3.sh C6 4838 || exit 1
touch $R/HOLD-C6; echo "$(date '+%F %T %Z') queue7 C6 done; HOLD-C6 set" >> $R/driver.log
