#!/bin/bash
export GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d
cd <HOME>/wt-pilot-1
echo "START $(date -Iseconds) head=$(git rev-parse HEAD)"
<HOME>/venv/bin/python -m obench.reflection.runner --config <HOME>/pilot-2/config.json --out <HOME>/pilot-2/run --cell --opencode <HOME>/h1/opencode-src/bin/<REDACTED_HEX>/opencode --use-image-tag --workers 8
echo "EXIT $? $(date -Iseconds)"
