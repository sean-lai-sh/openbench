#!/bin/bash
cd /workspace/openbench-ab
P2="11731 12214 13090 13198 13269 13331 17053 19058 21070 22390 23771 24974 25226 25431"
{
echo "# Phase 2 report (auto-generated $(date '+%Y-%m-%d %H:%M ET'))"
echo; echo "Worktree /workspace/openbench-ab @ 9abef63208c6f226b215bea884e84a322303bba2. Command per PR:"
echo '`python3 -m thesis.ab.run_ab thesis/ab/fixtures/opencode-harness-prs.csv --pr <PR> --trials 3 --jobs 8 --out results/ab --cache /workspace/openbench-ab/results/opencode-src` (driver results/ab-logs/phase2.sh; cap enforced by driver watchdog because runner --max-cost-usd halts on 623'"'"'s unmetered cells).'
echo; echo "Driver status:"; echo '```'; grep -E "===|STOP|CAP|END" results/ab-logs/phase2.log | grep -v "^ *1 " | tail -40; cat results/ab-logs/aa-driver.log 2>/dev/null; echo '```'
echo; echo "## Phase 2 PRs with real results"; python3 results/ab-logs/table.py $P2
echo; echo "## Noise references"; python3 results/ab-logs/table.py 17098-aa 18140 17098 26821
echo; echo "## Quarantined / incompatible (runner bugs, fix in PR #5)"
echo "- DecimalError (v0.14.7-v0.15.17): 3052, 3115, 3369, 3418 -> cells moved to results/ab-quarantine/phase2/decimalerror-*"
echo "- musl binary selected on glibc box (v1.0.79-v1.0.221): 4204, 4838, 5066, 5131, 5140, 5527, 6524 -> false incompatible sidecars moved to results/ab-quarantine/phase2/musl-binary-*"
for pr in $P2; do ls results/ab/$pr/*.incompatible.json 2>/dev/null; done
echo; echo "Cumulative est. spend (all phases): \$$(python3 results/ab-logs/p2stats.py total)"
} > results/ab-logs/phase2-report.md
