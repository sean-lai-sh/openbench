#!/bin/bash
set -euo pipefail
export GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d
cd <HOME>/wt-pilot-1
echo "START $(date -Iseconds) head=$(git rev-parse HEAD) dirty=$(git status --porcelain | wc -l)"
echo "pwd=$(pwd) python=$(<HOME>/venv/bin/python -c 'import obench.reflection.runner as r; print(r.__file__)')"
<HOME>/venv/bin/python -m obench.reflection.runner \
  --config <HOME>/pilot-smoke-640f-w1/config.json \
  --out <HOME>/pilot-smoke-640f-w1/run \
  --cell \
  --opencode <HOME>/h1/opencode-src/bin/<REDACTED_HEX>/opencode \
  --use-image-tag \
  --workers 1
echo "EXIT $? $(date -Iseconds)"
