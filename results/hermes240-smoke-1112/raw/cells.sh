#!/bin/bash
# Hermes #240 live smoke, one cell per model, sequential. Not scored.
cd ~/ob-h240 && . ~/venv/bin/activate
OUT=~/h2/hermes240-smoke-1112
git rev-parse HEAD > $OUT/head.txt; hostname -f > $OUT/host.txt
export PYTHONPATH=$HOME/ob-h240 GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d OBENCH_ADC_METADATA=1 OBENCH_CELL_IMAGE=h1-env:1027-strace
export OBENCH_HERMES_ROOT=$HOME/h1/hermes/<REDACTED_HEX>
export OBENCH_HERMES_BIN=$OBENCH_HERMES_ROOT/src/.hermes/bin/hermes
for m in claude-sonnet-5-5 claude-opus-5-5; do
  echo "=== $m start $(date -u +%FT%TZ)" >> $OUT/cells.log
  timeout 3000 python3 data/hermes-harness-smoke/cell.py --out "$OUT/$m" --exec docker --image h1-env:1027-strace --vertex-model $m >> $OUT/$m.out 2>&1
  echo "=== $m exit=$? end $(date -u +%FT%TZ)" >> $OUT/cells.log
done
echo ALL_DONE >> $OUT/cells.log
