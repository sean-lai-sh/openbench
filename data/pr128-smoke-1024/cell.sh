#!/bin/bash
set -u
export OBENCH_HARBOR_APP_REWRITE=1
git config --global --add safe.directory "*"
python3 -m venv /venv && /venv/bin/pip install -q -e /ob
OUT=/h2/smoke128/cell; mkdir -p $OUT
cd /ob && /venv/bin/python -m thesis.ab.run_ab /h2/h2prs.csv --pr 13331 --trials 1 \
 --tasks-dir /ob/data/packs/openbench-tb-hard --tasks polyglot-rust-c --timeout 2400 --timeout-cap-s 2400 --cell-meta \
 --jobs 2 --vertex-model claude-sonnet-5-5 --out $OUT --cache /h1/opencode-src --order interleave-seeded --seed 1024 \
 --max-cost-usd 4 > $OUT/run.log 2>&1
echo EXIT $? >> $OUT/run.log
