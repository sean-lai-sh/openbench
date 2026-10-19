# queue6: fresh C5 only (after PM HOLD/abort 2026-10-19). runbatch3.sh, same settings. Holds at HOLD-C5; C6 NOT started until PM confirms C5.
R=/workspace/openbench-ab/results/step6-opus-1017
[ -e $R/QUEUE-STOP ] && { echo "$(date '+%F %T %Z') queue6 halted: $(cat $R/QUEUE-STOP)" >> $R/driver.log; exit 1; }
bash $R/runbatch3.sh C5 21070,22390,23771,25431 || exit 1
touch $R/HOLD-C5; echo "$(date '+%F %T %Z') queue6 C5 done; HOLD-C5 set (C6 waits for PM confirmation of C5 PR)" >> $R/driver.log
