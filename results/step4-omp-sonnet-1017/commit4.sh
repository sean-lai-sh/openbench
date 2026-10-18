#!/bin/bash
# usage: commit4.sh <branch-label> "<title>" <results dir names...>  -> data PR via sparse worktree /tmp/ob-s4commit2; squash-merge; verify vs main.
set -e
L=$1; T=$2; shift 2; RES=/workspace/openbench-ab/results; PY=/workspace/openbench-ab/.venv/bin/python
cd /tmp/ob-s4commit2 && git fetch -q origin && git checkout -q -B data/s4-$L origin/main
for d in step4-omp-sonnet-1017 "$@"; do rm -rf results/$d; cp -a $RES/$d results/; find results/$d -name locks -type d -prune -exec rm -rf {} +; done
for x in ${EXCL:-}; do rm -rf results/step4-omp-sonnet-1017/$x; done
for f in $(find results/step4-omp-sonnet-1017* -type f -size +50M); do echo "$(stat -c %s $f) $(sha256sum $f | cut -d' ' -f1) ${f#results/}" >> results/step4-omp-sonnet-1017/MANIFEST-excluded.txt; rm -f $f; done
G="git -c user.name=sean-lai-sh -c user.email=sean-lai-sh@users.noreply.github.com"
git add -f results/step4-omp-sonnet-1017*; for d in "$@"; do git add -f results/$d; done; $G commit -qm "data: step-4 OMP Sonnet $T"
git push -q -f origin data/s4-$L 2>&1 | tail -1
B=""; for d in "$@"; do for s in $RES/$d/SUMMARY*.txt; do [ -f $s ] && B="$B$(cat $s)"$'\n'; done; done
gh pr create --repo sean-lai-sh/openbench --base main --head data/s4-$L --title "data: step-4 OMP Sonnet $T" --body "$(printf 'Data only (results/).\n```\n%s\n```\n' "$B")"
gh pr merge data/s4-$L --repo sean-lai-sh/openbench --squash
git fetch -q; git log origin/main --oneline -1
cd /tmp/ob-s4commit2 && for d in step4-omp-sonnet-1017 "$@"; do L2=$RES/$d; m=0; df=0; n=0; while IFS= read -r f; do n=$((n+1)); rel=results/$d/${f#$L2/}; h=$(git rev-parse -q --verify "origin/main:$rel") || { m=$((m+1)); continue; }; [ "$h" = "$(git hash-object "$f")" ] || df=$((df+1)); done < <(find $L2 -type f -not -path '*/locks/*' -size -50M); echo "$d: $n files, missing $m, differ $df"; done
