#!/bin/bash
# usage: commit_aa.sh <label>  -> data PR for results/step5-opus-aa-1017-<label> + step5 scripts; squash-merge; verify.
set -e
L=$1; RES=/workspace/openbench-ab/results; R=$RES/step5-opus-aa-1017; PY=/workspace/openbench-ab/.venv/bin/python; OUT=step5-opus-aa-1017-$L
$PY $R/aastats.py $RES/$OUT > $RES/$OUT/SUMMARY-$L.txt
echo "# Opus 5.5 A/A (--aa, parent both sides), 30/side, --order interleave-seeded --seed 1016, mirrors results/aa-sonnet-1016." >> $RES/$OUT/SUMMARY-$L.txt
cd /tmp/ob-fs && git fetch -q && git checkout -q -B data/s5-$L origin/main
for d in step5-opus-aa-1017 $OUT; do rm -rf results/$d; cp -a $RES/$d results/; find results/$d -name locks -type d -prune -exec rm -rf {} +; done
BIG=$(find results/step5-opus-aa-1017* -type f -size +50M); for f in $BIG; do echo "$(stat -c %s $f) $(sha256sum $f | cut -d' ' -f1) ${f#results/}" >> results/$OUT/MANIFEST-excluded.txt; rm -f $f; done
G="git -c user.name=sean-lai-sh -c user.email=sean-lai-sh@users.noreply.github.com"
git add -f results/step5-opus-aa-1017*; $G commit -qm "data: step-5 Opus A/A $L 30/side"
git push -q -f origin data/s5-$L 2>&1 | tail -1
gh pr create --repo sean-lai-sh/openbench --base main --head data/s5-$L --title "data: step-5 Opus A/A $L 30/side" --body "$(echo 'Data only (results/).'; echo '```'; cat results/$OUT/SUMMARY-$L.txt; echo '```')"
gh pr merge data/s5-$L --repo sean-lai-sh/openbench --squash
git fetch -q; git log origin/main --oneline -1
bash $RES/step4-omp-sonnet-1017/verify_main.sh step5-opus-aa-1017 $OUT | tail -3
