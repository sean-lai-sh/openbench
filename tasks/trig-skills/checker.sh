#!/usr/bin/env bash
# Runs with cwd set to a fresh copy of the task workspace.
# Exit 0 => `python3 main.py` runs and prints the expected line.
set -euo pipefail

EXPECTED="Hello, world!"

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
