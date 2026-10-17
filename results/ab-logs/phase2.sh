#!/bin/bash
cd /workspace/openbench-ab
export GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d VERTEX_LOCATION=global GOOGLE_APPLICATION_CREDENTIALS=/home/box/.config/gcloud/application_default_credentials.json
CAP=850; HEADROOM=40
PRS="3052 3115 3369 3418 4204 4838 5066 5131 5140 5527 6524 11731 12214 13090 13198 13269 13331 17053 19058 21070 22390 23771 24974 25226 25431"
S=results/ab-logs/p2stats.py
[ -f results/ab-logs/phase2-progress.md ] || printf "# Phase 2 progress\n\nCap: cumulative est. spend < \$$CAP (enforced by phase2.sh watchdog; runner --max-cost-usd unusable because 623's unmetered cells block all launches).\n" > results/ab-logs/phase2-progress.md
echo "PHASE2 START $(date -Is) spend=\$(python3 $S total)"
for pr in $PRS; do
  spent=$(python3 $S total)
  if python3 -c "import sys; sys.exit(0 if $spent + $HEADROOM > $CAP else 1)"; then
    echo "STOP before $pr: spend \$$spent + headroom \$$HEADROOM > cap \$$CAP"; echo -e "\n**STOPPED before PR $pr: spend \$$spent near cap**" >> results/ab-logs/phase2-progress.md; break
  fi
  echo "=== PR $pr start $(date -Is) spend=\$$spent"
  setsid python3 -m thesis.ab.run_ab thesis/ab/fixtures/opencode-harness-prs.csv --pr $pr --trials 3 --jobs 8 --out results/ab --cache /workspace/openbench-ab/results/opencode-src > results/ab-logs/p2-pr-$pr.log 2>&1 &
  rp=$!
  killed=0
  while kill -0 $rp 2>/dev/null; do
    sleep 30
    s=$(python3 $S total)
    if python3 -c "import sys; sys.exit(0 if $s > $CAP else 1)"; then
      echo "CAP HIT during $pr: \$$s; killing runner group $rp"; kill -- -$rp; sleep 5; kill -9 -- -$rp 2>/dev/null; killed=1; break
    fi
  done
  wait $rp; rc=$?
  echo "=== PR $pr exit $rc $(date -Is)"
  python3 $S quarantine $pr
  grep -E "429|RESOURCE_EXHAUSTED|incompatible|unmetered|stopped|launched" results/ab-logs/p2-pr-$pr.log | sort | uniq -c | head -10
  status="exit $rc, $(date '+%H:%M ET')"; [ $killed = 1 ] && status="KILLED at cap"
  python3 $S progress $pr "$status"
  [ $killed = 1 ] && break
done
echo "PHASE2 END $(date -Is) spend=\$(python3 $S total)"
