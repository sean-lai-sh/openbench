#!/bin/bash
# usage: commit7.sh <label> "<title>" <results dirs or files...>: sparse worktree /tmp/ob-s6commit, git add -f, sean-lai-sh identity, PR body = SUMMARY*.txt of given dirs, squash-merge, verify every file on origin/main.
set -e; L=$1; T=$2; shift 2; RES=/workspace/openbench-ab/results
M=$RES/step8-sonnet447-pilot-1020/MANIFEST-excluded.txt
for d in "$@"; do for f in $(cd $RES && find $d -type f -size +50M); do grep -qF " $f" $M 2>/dev/null || echo "$(stat -c %s $RES/$f) $(sha256sum $RES/$f | cut -d' ' -f1) $f" >> $M; done; done
cd /tmp/ob-s6commit; for d in "$@"; do git sparse-checkout add /results/$d >/dev/null 2>&1 || true; done; git fetch -q origin; git checkout -q -B data/s8-$L origin/main
for d in "$@" step7-opus-1019; do rm -rf results/$d; mkdir -p results/$(dirname $d); cp -a $RES/$d results/$d; [ -d results/$d ] && { find results/$d -name locks -type d -prune -exec rm -rf {} +; find results/$d -type f -size +50M -delete; }; done
G="git -c user.name=sean-lai-sh -c user.email=sean-lai-sh@users.noreply.github.com"
for d in "$@" step7-opus-1019; do git add -f results/$d; done
[ -z "$(git diff --cached --name-only | grep -v '^results/')" ] || { echo "NON-RESULTS FILES"; exit 1; }
$G commit -qm "data: step-8 Sonnet 447 pilot $T"; git push -q -f origin data/s8-$L 2>&1 | tail -1
B=""; for d in "$@"; do for s in $RES/$d/SUMMARY*.txt; do [ -f $s ] && B="$B$(cat $s)"$'\n'; done; done
gh pr create --repo sean-lai-sh/openbench --base main --head data/s8-$L --title "data: step-8 Sonnet 447 pilot $T" --body "$(printf 'Data only (results/).\n```\n%s\n```\n' "$B")"
gh pr merge data/s8-$L --repo sean-lai-sh/openbench --squash; git fetch -q; git log origin/main --oneline -1
for d in "$@" step7-opus-1019; do L2=$RES/$d; m=0; df=0; n=0; while IFS= read -r f; do n=$((n+1)); rel=results/$d${f#$L2}; h=$(git rev-parse -q --verify "origin/main:$rel") || { m=$((m+1)); continue; }; [ "$h" = "$(git hash-object "$f")" ] || df=$((df+1)); done < <(find $L2 -type f -not -path '*/locks/*' -size -50M); echo "$d: $n files, missing $m, differ $df"; [ $m -eq 0 ] && [ $df -eq 0 ] || BAD=1; done; [ -z "${BAD:-}" ] || { echo VERIFY FAILED; exit 1; }
