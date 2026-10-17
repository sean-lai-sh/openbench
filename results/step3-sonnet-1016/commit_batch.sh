#!/bin/bash
# usage: commit_batch.sh <src-dir-name> <label> PR...
set -e
SRCN=$1; LABEL=$2; shift 2
S=/workspace/openbench-ab/results/$SRCN
cd /tmp/ob-fs && git fetch -q && git checkout -q -B data/s3-$LABEL origin/main
mkdir -p results/$SRCN
for d in "$@"; do rm -rf results/$SRCN/$d; cp -a $S/$d results/$SRCN/; rm -rf results/$SRCN/$d/locks; done
rm -rf results/$SRCN/proxy-ledger; cp -a $S/proxy-ledger results/$SRCN/
cp /workspace/openbench-ab/results/step3-sonnet-1016/driver.log results/step3-sonnet-1016/
cp $S/*.log results/$SRCN/ 2>/dev/null || true
PY=/workspace/openbench-ab/.venv/bin/python
$PY /workspace/openbench-ab/results/step3-sonnet-1016/stats.py results/$SRCN > /tmp/st-all.txt
pat="^(pr$(printf '|%s' "$@")) "
grep -E "$pat" /tmp/st-all.txt > results/$SRCN/SUMMARY-$LABEL.txt
echo "# seeded order: --order interleave-seeded --seed 1016" >> results/$SRCN/SUMMARY-$LABEL.txt
G="git -c user.name=sean-lai-sh -c user.email=sean-lai-sh@users.noreply.github.com"
git add -f results/$SRCN results/step3-sonnet-1016/driver.log
$G commit -qm "data: step-3 Sonnet $LABEL ($*)"
git push -q origin data/s3-$LABEL 2>&1 | tail -1
gh pr create --repo sean-lai-sh/openbench --base main --head data/s3-$LABEL --title "data: step-3 Sonnet $LABEL ($*)" --body "$(echo '```'; cat results/$SRCN/SUMMARY-$LABEL.txt; echo '```'; echo 'Data only.')"
gh pr merge data/s3-$LABEL --repo sean-lai-sh/openbench --squash
git fetch -q; git log origin/main --oneline -1
