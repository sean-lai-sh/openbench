# Stop the smoke pair after the first row lands (one-cell smoke).
G=~/h2/hookfix-smoke-1103
for i in $(seq 1 400); do
  n=$(cat $G/2.0.50-5140/opus/5140/*.jsonl 2>/dev/null | wc -l)
  if [ "$n" -ge 1 ]; then echo "$(date) first row; stopping" >> $G/onecell.log; sudo docker stop -t 30 gate-2-0-50-5140 >> $G/onecell.log 2>&1; exit 0; fi
  sleep 5
done
