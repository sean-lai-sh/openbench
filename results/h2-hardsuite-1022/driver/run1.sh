#!/bin/bash
# usage (inside h2-env:1022): run1.sh <vertex-model> <out> <prs-csv-ids> <cap-usd> <jobs>
set -u
export OBENCH_HARBOR_APP_REWRITE=1
M=$1 OUT=$2 P=$3 CAP=$4 J=$5
T=dna-insert,filter-js-from-html,model-extraction-relu-logits,polyglot-rust-c,regex-chess,sam-cell-seg,torch-pipeline-parallelism,torch-tensor-parallelism,video-processing
git config --global --add safe.directory '*'
[ -x /venv/bin/python ] || { python3 -m venv /venv && /venv/bin/pip install -q -e /ob; }
mkdir -p $OUT
cd /ob && exec /venv/bin/python -m thesis.ab.run_ab /h2/h2prs.csv --pr $P --trials 10 \
  --tasks-dir /ob/data/packs/openbench-tb-hard --tasks $T --timeout 2400 --timeout-cap-s 2400 --cell-meta \
  --jobs $J --vertex-model $M --out $OUT --cache /h1/opencode-src --order interleave-seeded --seed 1022 \
  --max-cost-usd $CAP > $OUT/run.log 2>&1
