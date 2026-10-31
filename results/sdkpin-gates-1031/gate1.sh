#!/bin/bash
# sdkpin gate pair (inside h2-env:1022). Args: MODEL OUT PR PIN
# Same flags as /h2/sdkpin-test-1030/run1.sh except task model-extraction-relu-logits,
# --max-cost-usd 1.0, explicit OBENCH_ANTHROPIC_PIN (#207 override) and OBENCH_GATE_CELL=1.
set -u
MODEL=$1 OUT=$2 PR=$3 PIN=$4
export OBENCH_HARBOR_APP_REWRITE=1
export OBENCH_PROVIDER_PIN_ROOT=/h1/opencode-src/provider-pins
export OBENCH_ANTHROPIC_PIN=$PIN
export OBENCH_GATE_CELL=1
git config --global --add safe.directory "*"
[ -x /venv/bin/python ] || { python3 -m venv /venv && /venv/bin/pip install -q -e /ob; }
mkdir -p $OUT
cd /ob && git rev-parse HEAD > $OUT/runner_commit.txt
exec /venv/bin/python -m thesis.ab.run_ab /h2/h2prs.csv --pr $PR --trials 1 \
  --tasks-dir /ob/data/packs/openbench-tb-hard --tasks model-extraction-relu-logits --timeout 2400 --timeout-cap-s 2400 --cell-meta \
  --jobs 1 --vertex-model $MODEL --out $OUT --cache /h1/opencode-src --order interleave-seeded --seed 1022 \
  --max-cost-usd 1.0 > $OUT/run.log 2>&1
