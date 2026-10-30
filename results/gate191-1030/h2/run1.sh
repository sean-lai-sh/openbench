#!/bin/bash
set -u
export OBENCH_HARBOR_APP_REWRITE=1
git config --global --add safe.directory '*'
[ -x /venv/bin/python ] || { python3 -m venv /venv && /venv/bin/pip install -q -e /ob; }
mkdir -p /h2/out
cd /ob && exec /venv/bin/python -m thesis.ab.run_ab /h2/h2prs.csv --pr 4204 --trials 1 \
  --tasks-dir /ob/data/packs/openbench-tb-hard --tasks torch-tensor-parallelism --timeout 2400 --timeout-cap-s 2400 --cell-meta \
  --jobs 2 --vertex-model claude-opus-5-5 --out /h2/out/opus/4204 --cache /h1/opencode-src --order interleave-seeded --seed 1022 \
  --max-cost-usd 5 > /h2/out/run.log 2>&1
