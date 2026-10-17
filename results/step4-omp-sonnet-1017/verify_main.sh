# usage: verify_main.sh <results-subdir>...  compares every live file (minus locks/) with origin/main blob hashes.
cd /tmp/ob-fs && git fetch -q
for d in "$@"; do
  L=/workspace/openbench-ab/results/$d; miss=0; diff=0; n=0
  while IFS= read -r f; do n=$((n+1)); rel=results/$d/${f#$L/}
    h=$(git rev-parse -q --verify "origin/main:$rel" 2>/dev/null) || { miss=$((miss+1)); echo "MISSING $rel"; continue; }
    [ "$h" = "$(git hash-object "$f")" ] || { diff=$((diff+1)); echo "DIFF $rel"; }
  done < <(find $L -type f -not -path '*/locks/*' -size -50M)
  echo "$d: $n files, missing $miss, differ $diff"
done
