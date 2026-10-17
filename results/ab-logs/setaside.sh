#!/bin/bash
# Detached driver: re-run the 17 set-aside OpenCode A/B rows on aecd3fa (PR #5).
set -u
cd /workspace/openbench-ab
export GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d
export VERTEX_LOCATION=global
export GOOGLE_APPLICATION_CREDENTIALS=/home/box/.config/gcloud/application_default_credentials.json

CAP=800
HEADROOM=40
PRS="623 913 984 1248 2334 2367 3052 3115 3369 3418 4204 4838 5066 5131 5140 5527 6524"
S=results/ab-logs/setaside_stats.py
LOG=results/ab-logs/setaside-driver.log
FIXTURE=thesis/ab/fixtures/opencode-harness-prs.csv
CACHE=/workspace/openbench-ab/results/opencode-src

mkdir -p results/ab-logs results/ab
if [ ! -f results/ab-logs/setaside-progress.md ]; then
  printf "# Set-aside 17 progress\n\nWorktree @ aecd3fa (PR #5). Cap: cumulative est. spend < \$%s (phase ~\$400 / overall soft pause ~\$800 from prior ~\$414). Driver: results/ab-logs/setaside.sh.\n" "$CAP" > results/ab-logs/setaside-progress.md
fi

echo "SETASIDE START $(date -Is) spend=\$$(python3 $S total) HEAD=$(git rev-parse --short HEAD)"

regen_summary() {
  python3 -m thesis.ab.summarize "$FIXTURE" --results results/ab --out results/ab \
    >> results/ab-logs/setaside-summary-regen.log 2>&1 || \
    echo "SUMMARY REGEN failed rc=$? $(date -Is)"
}

for pr in $PRS; do
  spent=$(python3 $S total)
  if python3 -c "import sys; sys.exit(0 if float('$spent') + $HEADROOM > $CAP else 1)"; then
    msg="STOP before $pr: spend \$$spent + headroom \$$HEADROOM > cap \$$CAP"
    echo "$msg"
    echo -e "\n**STOPPED before PR $pr: spend \$$spent near cap**" >> results/ab-logs/setaside-progress.md
    echo "$msg" > results/ab-logs/setaside-latest.txt
    break
  fi
  echo "=== PR $pr start $(date -Is) spend=\$$spent"
  setsid python3 -m thesis.ab.run_ab "$FIXTURE" --pr "$pr" --trials 3 --jobs 8 \
    --out results/ab --cache "$CACHE" \
    > "results/ab-logs/setaside-$pr.log" 2>&1 &
  rp=$!
  killed=0
  while kill -0 $rp 2>/dev/null; do
    sleep 30
    s=$(python3 $S total)
    if python3 -c "import sys; sys.exit(0 if float('$s') > $CAP else 1)"; then
      echo "CAP HIT during $pr: \$$s; killing runner group $rp"
      kill -- -$rp 2>/dev/null
      sleep 5
      kill -9 -- -$rp 2>/dev/null
      killed=1
      break
    fi
  done
  wait $rp 2>/dev/null
  rc=$?
  echo "=== PR $pr exit $rc $(date -Is)"
  grep -E "429|RESOURCE_EXHAUSTED|incompatible|unmetered|stopped|launched|DecimalError|musl|infra" \
    "results/ab-logs/setaside-$pr.log" 2>/dev/null | sort | uniq -c | head -15 || true
  status="exit $rc, $(date '+%H:%M ET')"
  [ "$killed" = 1 ] && status="KILLED at cap"
  python3 $S progress "$pr" "$status"
  regen_summary
  [ "$killed" = 1 ] && break
done

echo "SETASIDE END $(date -Is) spend=\$$(python3 $S total)"
python3 $S report
regen_summary
echo "SETASIDE REPORT written $(date -Is)"
