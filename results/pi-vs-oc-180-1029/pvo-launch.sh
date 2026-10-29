cd ~/ob-pvo && . ~/venv/bin/activate
export PYTHONPATH=$HOME/ob-pvo GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d OBENCH_CELL_IMAGE=h1-env:1027-strace OBENCH_ADC_METADATA=1
export PI_NODE_PREFIX=$HOME/h1/toolchain/node-v22.19.0-linux-x64
export OPENCODE_SHA=ba54cee55e18b47fb70badc84ae2cbac7c83d258 OPENCODE_NODE_PREFIX=$HOME/h1/toolchain/node-v20.19.2-linux-x64
mkdir -p ~/pvo180; git rev-parse HEAD > ~/pvo180/head.txt; cp ~/pvo-batch.py ~/pvo-launch.sh ~/pvo180/
exec python3 ~/pvo-batch.py
