#!/bin/bash
# usage: commit6.sh <branch-label> "<title>" [extra results dirs...] -> stages EVERY step6-opus-1017* dir + extras via sparse worktree /tmp/ob-s6commit; squash-merge; verify every file vs origin/main (fails on any miss/diff). SUMDIRS = dirs whose SUMMARY*.txt go in the PR body.
set -e
L=$1; T=$2; shift 2; RES=/workspace/openbench-ab/results; PY=/workspace/openbench-ab/.venv/bin/python
# Stage EVERY step6-opus-1017* dir plus any extra dirs given (lesson of #94).
DIRS=$(cd $RES && ls -d step6-opus-1017* | sort -u; for d in "$@"; do echo $d; done); DIRS=$(echo "$DIRS" | sort -u)
# Files >50 MB: MANIFEST line (size sha256 path) written into the live dir first (dedup), file left on disk, not staged.
M=$RES/step6-opus-1017/MANIFEST-excluded.txt
for d in $DIRS; do for f in $(cd $RES && find $d -type f -size +50M); do grep -qF " $f" $M 2>/dev/null || echo "$(stat -c %s $RES/$f) $(sha256sum $RES/$f | cut -d' ' -f1) $f" >> $M; done; done
cd /tmp/ob-s6commit && git fetch -q origin && git checkout -q -B data/s6-$L origin/main
for d in $DIRS; do rm -rf results/$d; cp -a $RES/$d results/; find results/$d -name locks -type d -prune -exec rm -rf {} +; find results/$d -type f -size +50M -delete; done


G="git -c user.name=sean-lai-sh -c user.email=sean-lai-sh@users.noreply.github.com"
for d in $DIRS; do git add -f results/$d; done; $G commit -qm "data: step-6 Opus OpenCode $T"
git push -q -f origin data/s6-$L 2>&1 | tail -1
B=""; for d in ${SUMDIRS:-$*}; do for s in $RES/$d/SUMMARY*.txt; do [ -f $s ] && B="$B$(cat $s)"$'\n'; done; done
gh pr create --repo sean-lai-sh/openbench --base main --head data/s6-$L --title "data: step-6 Opus OpenCode $T" --body "$(printf 'Data only (results/).\n```\n%s\n```\n' "$B")"
gh pr merge data/s6-$L --repo sean-lai-sh/openbench --squash
git fetch -q; git log origin/main --oneline -1
cd /tmp/ob-s6commit && for d in $DIRS; do L2=$RES/$d; m=0; df=0; n=0; while IFS= read -r f; do n=$((n+1)); rel=results/$d/${f#$L2/}; h=$(git rev-parse -q --verify "origin/main:$rel") || { m=$((m+1)); continue; }; [ "$h" = "$(git hash-object "$f")" ] || df=$((df+1)); done < <(find $L2 -type f -not -path '*/locks/*' -size -50M); echo "$d: $n files, missing $m, differ $df"; [ $m -eq 0 ] && [ $df -eq 0 ] || BAD=1; done; [ -z "${BAD:-}" ] || { echo VERIFY FAILED; exit 1; }
