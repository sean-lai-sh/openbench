#!/bin/bash
# usage: rdy.sh <obdir> <outname> <args...>
OB=$1; N=$2; shift 2
sudo docker run --rm --network host ${EXTRA:-} -e OBENCH_PROVIDER_TRACE=${TRACE:-} -e OBENCH_CELL_IMAGE=${IMG:-h1-env:1027-strace} -e TZ=America/New_York -e PATH=/h1/opencode-src/go/1.24.6/bin:/h1/toolchain/node-v20.19.2-linux-x64/bin:/root/.local/bin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin -v $OB:/ob -v $HOME/h1:/h1 -v $HOME/s8f032:/c -v $HOME/s8ctl-f04:/cf -v $HOME/s8:/s8 -v $HOME/s8ready:/o -v $HOME/s8-3481local:/l ${IMG:-h1-env:1027-strace} bash -c "git config --global --add safe.directory '*'; python3 -m venv /venv && /venv/bin/pip install -q -e /ob && cd /ob && /venv/bin/python -m thesis.ab.step8_stub_ready --out /o/$N $*" > $HOME/s8ready/$N.log 2>&1
