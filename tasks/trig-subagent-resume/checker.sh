#!/usr/bin/env bash
# Binary check: `python3 main.py` must exit 0 and print the expected line.
set -euo pipefail

EXPECTED="Total: 5.0"

set +e
got="$(python3 main.py 2>/dev/null)"
status=$?
set -e

if [ "$status" -ne 0 ]; then
    echo "FAIL: python3 main.py exited with status $status" >&2
    if [ "$status" -eq 1 ]; then
        printf '%s\n' "OBENCH_VERDICT: fail"
        exit 1
    fi
    exit "$status"
fi

if [ "$got" != "$EXPECTED" ]; then
    echo "FAIL: unexpected output" >&2
    echo "--- expected ---" >&2
    printf '%s\n' "$EXPECTED" >&2
    echo "--- got ---" >&2
    printf '%s\n' "$got" >&2
    printf '%s\n' "OBENCH_VERDICT: fail"
    exit 1
fi

echo "main.py ran and printed the expected line."
printf '%s\n' "OBENCH_VERDICT: pass"
