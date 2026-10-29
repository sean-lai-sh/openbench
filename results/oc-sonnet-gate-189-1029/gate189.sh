set -x
cd ~/ob-pr134 && . ~/venv/bin/activate
export PYTHONPATH=$HOME/ob-pr134 GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d OBENCH_CELL_IMAGE=h1-env:1027-strace OBENCH_ADC_METADATA=1
export OPENCODE_SHA=ba54cee55e18b47fb70badc84ae2cbac7c83d258 OPENCODE_NODE_PREFIX=$HOME/h1/toolchain/node-v20.19.2-linux-x64
G=$HOME/gate189; mkdir -p $G
git rev-parse HEAD > $G/head.txt
timeout 2700 python3 data/opencode-harness-smoke/cell.py --out $G/opencode --exec docker --image h1-env:1027-strace --cache $HOME/h1/opencode-src --sha $OPENCODE_SHA --node $OPENCODE_NODE_PREFIX --vertex-model claude-sonnet-5-5 --require-model-match > $G/oc.out 2>&1; echo OCEXIT $?
echo ALLDONE
