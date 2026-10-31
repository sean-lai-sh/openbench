S=~/h2/sdkpin-gates-1031-rerun
for d in $S/*-*/opus; do p=$(basename $(dirname $d)); [ "$p" = ua-probe ] && continue
 echo "== $p capped=$( [ -e $(dirname $d)/CAPPED ] && cat $(dirname $d)/CAPPED || echo no)"
 for f in $(sudo find $d -path "*cells/*/1.json"); do arm=$(echo $f | grep -oE "cells/[a-z]+" | cut -d/ -f2)
  sudo python3 -c "import json,sys;r=json.load(open(sys.argv[1]));print(' ',sys.argv[2],{k:r.get(k) for k in ['loaded_anthropic','status','stop_reason','cost_usd','runner_commit','reward']})" $f $arm; done
 sudo grep -ohE "\"loaded_anthropic\": *\"[^\"]*\"" $d/proxy-ledger/*.jsonl | sort | uniq -c | sed 's/^/  ledger /'
done
