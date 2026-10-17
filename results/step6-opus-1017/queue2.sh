# 13331, 24974, 25226 after runner PR #81 (Opus sampling strip). One PR at a time; each waits for the previous run.sh to exit.
R=/workspace/openbench-ab/results/step6-opus-1017; PY=/workspace/openbench-ab/.venv/bin/python
for PR in 13331 24974 25226; do
  [ -e $R/QUEUE-STOP ] && { echo "$(date '+%F %T %Z') queue2 halted before $PR: $(cat $R/QUEUE-STOP)" >> $R/driver.log; exit 1; }
  $PY $R/mkworktrees.py $PR 2>&1 | grep -E "^$PR " >> $R/worktrees.txt
  echo "$(date '+%F %T %Z') worktrees $PR: $(grep "^$PR " $R/worktrees.txt | awk '{print $3" "$4}' | sort -u | tr '\n' ' ')" >> $R/driver.log
  bash $R/run.sh $PR || exit 1
  echo "$(date '+%F %T %Z') queue2 done $PR" >> $R/driver.log
done
