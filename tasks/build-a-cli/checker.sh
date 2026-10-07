#!/usr/bin/env bash
# Runs with cwd set to a fresh copy of the task workspace (which should now
# contain the agent's wordcount.py). Test inputs and expected outputs live in
# the task's own checker_data/ directory, referenced via $TASK_DIR.
# Exit 0 => all cases pass, nonzero => failed.
set -euo pipefail

DATA="$TASK_DIR/checker_data"

if [ ! -f wordcount.py ]; then
    echo "FAIL: wordcount.py not found in workspace" >&2
    printf '%s\n' "OBENCH_VERDICT: fail"
    exit 1
fi

# Each entry: "<case name> <N>"
cases="case1 3
case2 2
case3 5"

fail=0
while read -r name n; do
    [ -z "$name" ] && continue
    set +e
    got="$(python3 wordcount.py "$DATA/$name.txt" "$n")"
    status=$?
    set -e
    if [ "$status" -ne 0 ] && [ "$status" -ne 1 ]; then
        echo "FAIL: $name command exited $status" >&2
        exit "$status"
    fi
    want="$(cat "$DATA/$name.expected")"
    if [ "$status" -ne 0 ] || [ "$got" != "$want" ]; then
        echo "FAIL: $name (N=$n)" >&2
        echo "--- expected ---" >&2
        printf '%s\n' "$want" >&2
        echo "--- got ---" >&2
        printf '%s\n' "$got" >&2
        fail=1
    fi
done <<EOF
$cases
EOF

if [ "$fail" -ne 0 ]; then
    printf '%s\n' "OBENCH_VERDICT: fail"
    exit 1
fi
echo "All wordcount cases passed."
printf '%s\n' "OBENCH_VERDICT: pass"
