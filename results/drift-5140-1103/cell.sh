#!/bin/bash
set -u
M=$1 PR=$2 PIN=$3 OUT=$4 SRC=$5 CELLS=${6:-}
export OBENCH_HARBOR_APP_REWRITE=1 OBENCH_PROVIDER_PIN_ROOT=/h1/opencode-src/provider-pins OBENCH_ANTHROPIC_PIN=$PIN
T=dna-insert,filter-js-from-html,model-extraction-relu-logits,polyglot-rust-c,regex-chess,sam-cell-seg,torch-pipeline-parallelism,torch-tensor-parallelism,video-processing
git config --global --add safe.directory '*'
[ -x /venv/bin/python ] || { python3 -m venv /venv && /venv/bin/pip install -q -e /ob; }
mkdir -p $OUT; cd /ob
X=(); [ -n "$CELLS" ] && X=(--cells "$CELLS")
exec /venv/bin/python -m thesis.ab.run_ab /h2/h2prs.csv --pr $PR --trials 10 --tasks-dir /ob/data/packs/openbench-tb-hard --tasks $T \
 --timeout 2400 --timeout-cap-s 2400 --cell-meta --jobs 4 --vertex-model $M --out $OUT --rerun-from $SRC --cache /h1/opencode-src \
 --order interleave-seeded --seed 1022 --runner-commit $OBENCH_RUNNER_COMMIT "${X[@]}" > $OUT/run.log 2>&1
