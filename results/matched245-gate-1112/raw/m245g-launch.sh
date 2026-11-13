cd ~/ob-m245g && . ~/venv/bin/activate
export PYTHONPATH=$HOME/ob-m245g GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d OBENCH_CELL_IMAGE=h1-env:1027-strace OBENCH_ADC_METADATA=1
export PI_NODE_PREFIX=$HOME/h1/toolchain/node-v22.19.0-linux-x64
export OPENCODE_SHA=ba54cee55e18b47fb70badc84ae2cbac7c83d258 OPENCODE_NODE_PREFIX=$HOME/h1/toolchain/node-v20.19.2-linux-x64
OUT=~/h2/matched245-gate-1112; mkdir -p $OUT; git rev-parse HEAD > $OUT/head.txt; hostname -f > $OUT/host.txt
cp ~/h2/m245g-batch.py ~/h2/m245g-launch.sh $OUT/
exec python3 $OUT/m245g-batch.py
