#!/bin/bash
# Detached driver: re-run the 17 set-aside OpenCode A/B rows on e04d456 (PR #6 proxy metering).
set -u
cd /workspace/openbench-ab
export GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d
export VERTEX_LOCATION=global
export GOOGLE_APPLICATION_CREDENTIALS=/home/box/.config/gcloud/application_default_credentials.json
export SETASIDE_ROUND=2

CAP=900
HEADROOM=40
PRS="623 913 984 1248 2334 2367 3052 3115 3369 3418 4204 4838 5066 5131 5140 5527 6524"
S=results/ab-logs/setaside_stats.py
LOG=results/ab-logs/setaside2-driver.log
FIXTURE=thesis/ab/fixtures/opencode-harness-prs.csv
CACHE=/workspace/openbench-ab/results/opencode-src

mkdir -p results/ab-logs results/ab
printf "# Set-aside 17 progress (round 2 @ e04d456 / PR #6)\n\nCap soft: cumulative est. spend pause around \$800–1000 (driver CAP=%s, HEADROOM=%s). Prior spend ~\$414; phase for 17 ~\$350–400. Smoke #17098 A/A passed first.\n\n" "$CAP" "$HEADROOM" > results/ab-logs/setaside2-progress.md
echo "starting" > results/ab-logs/setaside2-latest.txt
echo "SETASIDE2 START $(date -Is) spend=\$$(python3 $S total) HEAD=$(git rev-parse --short HEAD)" | tee -a "$LOG"

regen_summary() {
  python3 -m thesis.ab.summarize "$FIXTURE" --results results/ab --out results/ab \
    >> results/ab-logs/setaside2-summary-regen.log 2>&1 || \
    echo "SUMMARY REGEN failed rc=$? $(date -Is)" | tee -a "$LOG"
}

append_sdk() {
  local pr=$1
  python3 - <<PY
import json, os
pr="$pr"
lines=[]
for side in ("without","with"):
    p=f"results/ab/{pr}/{side}.toolchain.json"
    if os.path.exists(p):
        try:
            t=json.load(open(p))
            lines.append(f"{side}: bun={t.get('bun')}, ai={t.get('ai')}, anthropic={t.get('anthropic')}")
        except Exception as e:
            lines.append(f"{side}: toolchain unreadable ({e})")
    else:
        lines.append(f"{side}: (no toolchain)")
# sdk_changed from summarize row if present
changed=""
try:
    import csv
    with open("results/ab/summary.csv") as f:
        for r in csv.DictReader(f):
            if str(r.get("pr"))==str(pr):
                changed=r.get("sdk_changed") or ""
                break
except Exception:
    pass
with open("results/ab-logs/setaside2-progress.md","a") as fh:
    fh.write(f"- SDK: {'; '.join(lines)}; sdk_changed={changed!r}\n")
print("SDK", pr, "; ".join(lines), "sdk_changed=", changed)
PY
}

for pr in $PRS; do
  spent=$(python3 $S total)
  if python3 -c "import sys; sys.exit(0 if float('$spent') + $HEADROOM > $CAP else 1)"; then
    msg="STOP before $pr: spend \$$spent + headroom \$$HEADROOM > cap \$$CAP"
    echo "$msg" | tee -a "$LOG"
    echo -e "\n**STOPPED before PR $pr: spend \$$spent near cap**" >> results/ab-logs/setaside2-progress.md
    echo "$msg" > results/ab-logs/setaside2-latest.txt
    break
  fi
  echo "=== PR $pr start $(date -Is) spend=\$$spent" | tee -a "$LOG"
  echo "PR $pr running (spend=\$$spent)" > results/ab-logs/setaside2-latest.txt
  setsid python3 -m thesis.ab.run_ab "$FIXTURE" --pr "$pr" --trials 3 --jobs 8 \
    --out results/ab --cache "$CACHE" \
    > "results/ab-logs/setaside2-$pr.log" 2>&1 &
  rp=$!
  killed=0
  while kill -0 $rp 2>/dev/null; do
    sleep 30
    s=$(python3 $S total)
    if python3 -c "import sys; sys.exit(0 if float('$s') > $CAP else 1)"; then
      echo "CAP HIT during $pr: \$$s; killing runner group $rp" | tee -a "$LOG"
      kill -- -$rp 2>/dev/null
      sleep 5
      kill -9 -- -$rp 2>/dev/null
      killed=1
      break
    fi
  done
  wait $rp 2>/dev/null
  rc=$?
  echo "=== PR $pr exit $rc $(date -Is)" | tee -a "$LOG"
  # ConnectionReset / metering signals
  {
    echo "--- signals ---"
    rg -c 'ConnectionResetError' "results/ab-logs/setaside2-$pr.log" 2>/dev/null | awk '{print "ConnectionResetError_count="$1}'
    rg -c 'BrokenPipeError' "results/ab-logs/setaside2-$pr.log" 2>/dev/null | awk '{print "BrokenPipeError_count="$1}'
    grep -E "429|RESOURCE_EXHAUSTED|incompatible|unmetered|stopped|launched|DecimalError|musl|infra|proxy_measured" \
      "results/ab-logs/setaside2-$pr.log" 2>/dev/null | sort | uniq -c | head -20
  } | tee -a "$LOG" || true
  status="exit $rc, $(date '+%H:%M ET')"
  [ "$killed" = 1 ] && status="KILLED at cap"
  python3 $S progress "$pr" "$status"
  append_sdk "$pr"
  regen_summary
  echo "PR $pr done rc=$rc spend=\$$(python3 $S total)" > results/ab-logs/setaside2-latest.txt
  [ "$killed" = 1 ] && break
done

echo "SETASIDE2 END $(date -Is) spend=\$$(python3 $S total)" | tee -a "$LOG"
# final report
python3 $S report
# ensure header notes round 2
if [ -f results/ab-logs/setaside2-report.md ]; then
  # prepend round-2 banner once
  if ! head -1 results/ab-logs/setaside2-report.md | grep -q 'round 2'; then
    {
      echo "# Set-aside 17 report (round 2 @ e04d456 / PR #6)"
      echo
      echo "Generated $(date -Is). Soft cap CAP=$CAP. See also setaside2-progress.md."
      echo
      cat results/ab-logs/setaside2-report.md
    } > results/ab-logs/setaside2-report.md.tmp && mv results/ab-logs/setaside2-report.md.tmp results/ab-logs/setaside2-report.md
  fi
fi
regen_summary
echo "SETASIDE2 REPORT written $(date -Is)" | tee -a "$LOG"
echo "done spend=\$$(python3 $S total)" > results/ab-logs/setaside2-latest.txt
