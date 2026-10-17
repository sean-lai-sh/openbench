# Sequential queue after 913: one PR at a time. Waits for the previous PR's full run to end, stops if QUEUE-STOP exists.
R=/workspace/openbench-ab/results/step6-opus-1017; PY=/workspace/openbench-ab/.venv/bin/python
prev=913
for PR in 3052 26821 13331 24974 25226; do
  until grep -q "end full$prev " $R/driver.log || grep -q "smoke $prev FAILED" $R/driver.log; do sleep 30; done
  [ -e $R/QUEUE-STOP ] && { echo "$(date '+%F %T %Z') queue halted before $PR: $(cat $R/QUEUE-STOP)" >> $R/driver.log; exit 1; }
  $PY $R/mkworktrees.py $PR 2>&1 | grep -E "^$PR " >> $R/worktrees.txt
  echo "$(date '+%F %T %Z') worktrees $PR: $(grep "^$PR " $R/worktrees.txt | awk '{print $3" "$4}' | tr '\n' ' ')" >> $R/driver.log
  bash $R/run.sh $PR || exit 1
  prev=$PR
done
