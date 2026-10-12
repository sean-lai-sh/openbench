#!/usr/bin/env bash
set -euo pipefail
exec python3 "$TASK_DIR/checker_data/check.py"
