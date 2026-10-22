#!/bin/bash
# Step-8 full queue: smoke (1/side) of F01, then F01..F16 at 30/side, each batch as sub-invocations of <=11 PRs into step8-full413-1020-Fnn. Stops on QUEUE-STOP or HOLD.
R=/workspace/openbench-ab/results; S=$R/step8-full413-1020
B1=$(awk '$1=="F01"{print $2}' $S/BATCHES.txt)
[ -d $R/step8-full413-1020-smoke ] && [ -e $S/SMOKE-DONE ] || { bash $S/run.sh $R/step8-full413-1020-smoke smoke 1 $B1; touch $S/SMOKE-DONE; }
while read b prs; do
  [[ $b == F* ]] || continue; [ -e $S/DONE-$b ] && continue
  IFS=, read -ra A <<< "$prs"; i=0
  while [ $i -lt ${#A[@]} ]; do
    sub=$(IFS=,; echo "${A[*]:$i:11}"); k=$((i/11+1))
    [ -e $S/QUEUE-STOP ] && exit 1; [ -e $S/HOLD ] && exit 0
    [ -e $S/DONE-$b-$k ] || { bash $S/run.sh $R/step8-full413-1020-$b $b-$k 30 $sub && [ ! -e $S/QUEUE-STOP ] && touch $S/DONE-$b-$k; }
    i=$((i+11))
  done
  [ -e $S/QUEUE-STOP ] && exit 1
  touch $S/DONE-$b; echo "$(date '+%F %T %Z') batch $b complete" >> $S/driver.log
done < $S/BATCHES.txt
echo "$(date '+%F %T %Z') all batches complete" >> $S/driver.log
