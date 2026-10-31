#!/bin/bash
# sdkpin gate cell (inside h2-env:1022). Args: MODEL OUT PR PIN [TASK] [CAP]
# The driver passes OBENCH_RUNNER_COMMIT and OBENCH_CELL_IMAGE from the host:
# /ob is a worktree whose git dir is not mounted, so git rev-parse here prints
# nothing, and the image name is not visible from inside the container.
set -u
MODEL=$1 OUT=$2 PR=$3 PIN=$4 TASK=${5:-model-extraction-relu-logits} CAP=${6:-1.0}
: "${OBENCH_RUNNER_COMMIT:?driver must pass OBENCH_RUNNER_COMMIT}"
: "${OBENCH_CELL_IMAGE:?driver must pass OBENCH_CELL_IMAGE}"
export OBENCH_RUNNER_COMMIT OBENCH_CELL_IMAGE
export OBENCH_HARBOR_APP_REWRITE=1
export OBENCH_PROVIDER_PIN_ROOT=${OBENCH_PROVIDER_PIN_ROOT:-/h1/opencode-src/provider-pins}
export OBENCH_ANTHROPIC_PIN=$PIN
export OBENCH_GATE_CELL=1
[ -x /venv/bin/python ] || { python3 -m venv /venv && /venv/bin/pip install -q -e /ob; }
mkdir -p "$OUT"
cd /ob
echo "$OBENCH_RUNNER_COMMIT" > "$OUT/runner_commit.txt"
echo "$OBENCH_CELL_IMAGE" > "$OUT/cell_image.txt"
exec /venv/bin/python -m thesis.ab.run_ab /h2/h2prs.csv --pr "$PR" --trials 1 \
  --tasks-dir /ob/data/packs/openbench-tb-hard --tasks "$TASK" --timeout 2400 --timeout-cap-s 2400 --cell-meta \
  --jobs 1 --vertex-model "$MODEL" --out "$OUT" --cache /h1/opencode-src --order interleave-seeded --seed 1022 \
  --runner-commit "$OBENCH_RUNNER_COMMIT" \
  --max-cost-usd "$CAP" > "$OUT/run.log" 2>&1
