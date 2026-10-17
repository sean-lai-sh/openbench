#!/bin/bash
# usage: commit_pr.sh <PR> [extra results/ dir names...]  -> data PR (results/ only), squash-merge, verify vs main.
set -e
PR=$1; shift; RES=/workspace/openbench-ab/results; R=$RES/step6-opus-1017; PY=/workspace/openbench-ab/.venv/bin/python
OUT=step6-opus-1017-$PR; SM=step6-opus-1017-$PR-smoke
$PY $R/stats.py $RES/$OUT > $RES/$OUT/SUMMARY-$PR.txt; echo "# Opus 5.5 (--vertex-model claude-opus-5-5), OpenCode, --order interleave-seeded --seed 1016, 30/side. Opus A/A band not measured yet: CI-excludes-0 rows are FLAGGED, not labeled effects." >> $RES/$OUT/SUMMARY-$PR.txt
python3 $R/behaviour.py $RES/$OUT $PR >> $RES/$OUT/SUMMARY-$PR.txt
$PY $R/stats.py $RES/$SM > $RES/$SM/SUMMARY-smoke$PR.txt
cd /tmp/ob-fs && git fetch -q && git checkout -q -B data/s6-$PR origin/main
for d in step6-opus-1017 $OUT $SM "$@"; do rm -rf results/$d; cp -a $RES/$d results/; find results/$d -name locks -type d -prune -exec rm -rf {} +; done
BIG=$(find results/step6-opus-1017* -type f -size +50M)
if [ -n "$BIG" ]; then for f in $BIG; do echo "$(stat -c %s $f) $(sha256sum $f | cut -d' ' -f1) ${f#results/}" >> results/$OUT/MANIFEST-excluded.txt; rm -f $f; done; fi
G="git -c user.name=sean-lai-sh -c user.email=sean-lai-sh@users.noreply.github.com"
git add -f results/step6-opus-1017*; $G commit -qm "data: step-6 Opus OpenCode $PR 30/side (pulled forward)"
git push -q -f origin data/s6-$PR 2>&1 | tail -1
gh pr create --repo sean-lai-sh/openbench --base main --head data/s6-$PR --title "data: step-6 Opus OpenCode $PR 30/side (pulled forward)" --body "$(echo 'Data only (results/).'; echo '```'; cat results/$OUT/SUMMARY-$PR.txt; echo '```')"
gh pr merge data/s6-$PR --repo sean-lai-sh/openbench --squash
git fetch -q; git log origin/main --oneline -1
bash $RES/step4-omp-sonnet-1017/verify_main.sh step6-opus-1017 $OUT $SM "$@" | tail -6
