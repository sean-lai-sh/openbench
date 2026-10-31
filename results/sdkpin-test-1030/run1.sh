#!/bin/bash
# #207 test pair: h2-hardsuite-1022 opus PR 4204 dna-insert trial 1, both sides, in h2-env:1022.
# Same flags as /h2/run1.sh except --tasks dna-insert --trials 1 --jobs 1 --max-cost-usd 2.
set -u
export OBENCH_HARBOR_APP_REWRITE=1
export OBENCH_PROVIDER_PIN_ROOT=/h1/opencode-src/provider-pins
OUT=/h2/sdkpin-test-1030/opus
git config --global --add safe.directory "*"
[ -x /venv/bin/python ] || { python3 -m venv /venv && /venv/bin/pip install -q -e /ob; }
mkdir -p $OUT
cd /ob && git rev-parse HEAD > $OUT/runner_commit.txt
exec /venv/bin/python -m thesis.ab.run_ab /h2/h2prs.csv --pr 4204 --trials 1 \
  --tasks-dir /ob/data/packs/openbench-tb-hard --tasks dna-insert --timeout 2400 --timeout-cap-s 2400 --cell-meta \
  --jobs 1 --vertex-model claude-opus-5-5 --out $OUT --cache /h1/opencode-src --order interleave-seeded --seed 1022 \
  --max-cost-usd 2 "$@" > $OUT/run${DRY:+-dry}.log 2>&1
