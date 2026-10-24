#!/bin/bash
# One Pi smoke cell per model (claude-opus-5-5, claude-sonnet-5-5) on
# polyglot-rust-c. Builds pin d0aa218cb16c333c008f6aa3dcd670ac8b68383c and
# routes Anthropic /v1/messages through the Vertex proxy. Does not set
# OBENCH_PI_VERTEX. Needs GOOGLE_CLOUD_PROJECT and ADC. Smoke output is not
# a scored campaign.
set -u
export OBENCH_HARBOR_APP_REWRITE=1
git config --global --add safe.directory "*"
python3 -m venv /venv && /venv/bin/pip install -q -e /ob
OUT="${1:-/h2/pi-harness-smoke}"
mkdir -p "$OUT"
cd /ob && /venv/bin/python data/pi-harness-smoke/cell.py --out "$OUT" \
  > "$OUT/run.log" 2>&1
echo EXIT $? >> "$OUT/run.log"
