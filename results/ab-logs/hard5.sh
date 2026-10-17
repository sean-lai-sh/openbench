#!/bin/bash
# Detached driver: harder-task 5-trial A/B for cleared-noise PRs on e04d456.
set -u
cd /workspace/openbench-ab
export GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d
export VERTEX_LOCATION=global
export GOOGLE_APPLICATION_CREDENTIALS=/home/box/.config/gcloud/application_default_credentials.json

# Soft cap: prior ~$432; est ~$40–50/PR → ~$200–250 phase; pause past ~$700 total.
CAP=700
HEADROOM=40
PRS="26821 13331 23771 2334 3115"
S=results/ab-logs/hard5_stats.py
LOG=results/ab-logs/hard5-driver.log
FIXTURE=thesis/ab/fixtures/opencode-harness-prs.csv
CACHE=/workspace/openbench-ab/results/opencode-src

mkdir -p results/ab-logs results/ab results/ab-quarantine

# Record prior spend BEFORE wipe (includes 3-trial for these PRs).
if [ ! -f results/ab-logs/hard5-prior.txt ]; then
  python3 -c "
import json,glob
from thesis.ab.summarize import row_cost
t=0.0
for p in glob.glob('results/ab/*/cells/*/*/*.json'):
  try:
    c=row_cost(json.load(open(p)))
    t += c or 0
  except: pass
print(f'{t:.2f}')
" > results/ab-logs/hard5-prior.txt
fi
PRIOR=$(cat results/ab-logs/hard5-prior.txt)

# Wipe live cells for target PRs (quarantine copies already done by launcher).
for pr in $PRS; do
  if [ -d "results/ab/$pr/cells" ]; then
    rm -rf "results/ab/$pr/cells" "results/ab/$pr/locks"
    rm -f "results/ab/$pr"/without.jsonl "results/ab/$pr"/with.jsonl
    rm -f "results/ab/$pr"/without.toolchain.json "results/ab/$pr"/with.toolchain.json
    rm -f "results/ab/$pr"/without.incompatible.json "results/ab/$pr"/with.incompatible.json
    rm -f "results/ab/$pr"/without.infra.json "results/ab/$pr"/with.infra.json
  fi
done

# Live total after wipe (= prior minus wiped 3-trial costs).
python3 -c "
import json,glob
from thesis.ab.summarize import row_cost
t=0.0
for p in glob.glob('results/ab/*/cells/*/*/*.json'):
  try:
    c=row_cost(json.load(open(p)))
    t += c or 0
  except: pass
print(f'{t:.2f}')
" > results/ab-logs/hard5-live0.txt
LIVE0=$(cat results/ab-logs/hard5-live0.txt)

printf "# Harder-task 5-trial progress (@ e04d456 / PR #6)\n\n" > results/ab-logs/hard5-progress.md
{
  echo "PRs (order): 26821, 13331, 23771, 2334, 3115."
  echo "Command: \`python3 -m thesis.ab.run_ab $FIXTURE --pr <PR> --trials 5 --jobs 8 --out results/ab --cache $CACHE\` (all 8 core tasks)."
  echo "Soft cap CAP=\$$CAP HEADROOM=\$$HEADROOM. Prior cumulative ~\$$PRIOR; phase est ~\$200–250; pause past ~\$700."
  echo "3-trial cells quarantined under \`results/ab-quarantine/pre-hard5-<pr>/\` then wiped so run_ab does not skip trials 1–3."
  echo "Noise floor (first-pass A/A): ±12% wall, ±19% tokens, ±11% cost — applies to 26821/13331/23771."
  echo "2334/3115: set-aside 3-trial was tiny (~5s/16k, pass 0→0); prior CLEAR not confirmed under that floor."
  echo "Report tok and cost Δ% side by side; FLAG if |tok Δ% − cost Δ%| > 5pp."
  echo
  echo "Prior=\$$PRIOR live0_after_wipe=\$$LIVE0 HEAD=$(git rev-parse --short HEAD) started $(date -Is)."
  echo
} >> results/ab-logs/hard5-progress.md

echo "starting prior=\$$PRIOR live0=\$$LIVE0" > results/ab-logs/hard5-latest.txt
echo "HARD5 START $(date -Is) prior=\$$PRIOR live0=\$$LIVE0 HEAD=$(git rev-parse --short HEAD)" | tee -a "$LOG"

regen_summary() {
  python3 -m thesis.ab.summarize "$FIXTURE" --results results/ab --out results/ab \
    >> results/ab-logs/hard5-summary-regen.log 2>&1 || \
    echo "SUMMARY REGEN failed rc=$? $(date -Is)" | tee -a "$LOG"
}

append_sdk() {
  local pr=$1
  python3 - <<PY
import json, os, csv
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
changed=""
try:
    with open("results/ab/summary.csv") as f:
        for r in csv.DictReader(f):
            if str(r.get("pr"))==str(pr):
                changed=r.get("sdk_changed") or ""
                break
except Exception:
    pass
with open("results/ab-logs/hard5-progress.md","a") as fh:
    fh.write(f"- SDK: {'; '.join(lines)}; sdk_changed={changed!r}\n")
print("SDK", pr, "; ".join(lines), "sdk_changed=", changed)
PY
}

for pr in $PRS; do
  spent=$(python3 $S total)
  if python3 -c "import sys; sys.exit(0 if float('$spent') + $HEADROOM > $CAP else 1)"; then
    msg="STOP before $pr: spend \$$spent + headroom \$$HEADROOM > cap \$$CAP"
    echo "$msg" | tee -a "$LOG"
    echo -e "\n**STOPPED before PR $pr: spend \$$spent near cap**" >> results/ab-logs/hard5-progress.md
    echo "$msg" > results/ab-logs/hard5-latest.txt
    break
  fi
  echo "=== PR $pr start $(date -Is) spend=\$$spent" | tee -a "$LOG"
  echo "PR $pr running (spend=\$$spent)" > results/ab-logs/hard5-latest.txt
  setsid python3 -m thesis.ab.run_ab "$FIXTURE" --pr "$pr" --trials 5 --jobs 8 \
    --out results/ab --cache "$CACHE" \
    > "results/ab-logs/hard5-$pr.log" 2>&1 &
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
  {
    echo "--- signals ---"
    rg -c 'ConnectionResetError' "results/ab-logs/hard5-$pr.log" 2>/dev/null | awk '{print "ConnectionResetError_count="$1}'
    rg -c 'BrokenPipeError' "results/ab-logs/hard5-$pr.log" 2>/dev/null | awk '{print "BrokenPipeError_count="$1}'
    rg -c 'proxy_measured' "results/ab-logs/hard5-$pr.log" 2>/dev/null | awk '{print "proxy_measured_lines="$1}'
    grep -E "429|RESOURCE_EXHAUSTED|incompatible|unmetered|stopped|launched|DecimalError|musl|infra|proxy_measured|SDK" \
      "results/ab-logs/hard5-$pr.log" 2>/dev/null | sort | uniq -c | head -20
  } | tee -a "$LOG" || true
  status="exit $rc, $(date '+%H:%M ET')"
  [ "$killed" = 1 ] && status="KILLED at cap"
  python3 $S progress "$pr" "$status"
  append_sdk "$pr"
  regen_summary
  echo "PR $pr done rc=$rc spend=\$$(python3 $S total)" > results/ab-logs/hard5-latest.txt
  [ "$killed" = 1 ] && break
done

echo "HARD5 END $(date -Is) spend=\$$(python3 $S total)" | tee -a "$LOG"
python3 $S report
# prepend banner once
if [ -f results/ab-logs/hard5-report.md ]; then
  if ! head -1 results/ab-logs/hard5-report.md | grep -q 'Harder-task 5-trial'; then
    {
      echo "# Harder-task 5-trial A/B report (@ e04d456 / PR #6)"
      echo
      echo "Generated $(date -Is). Soft cap CAP=$CAP. See also hard5-progress.md."
      echo
      cat results/ab-logs/hard5-report.md
    } > results/ab-logs/hard5-report.md.tmp && mv results/ab-logs/hard5-report.md.tmp results/ab-logs/hard5-report.md
  fi
fi
regen_summary
echo "HARD5 REPORT written $(date -Is)" | tee -a "$LOG"
echo "done spend=\$$(python3 $S total)" > results/ab-logs/hard5-latest.txt
