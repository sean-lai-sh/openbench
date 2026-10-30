#!/bin/bash
# H2 driver (VM host). Pre-reg v2 + A1 + A2, sha256 a8668fc6641bc9eeb855065688fbbc02a0d3754c0021013e5169b4b0b0b88814
# Sean approved via PM 2026-10-22 (hard-suite cap $5K); executor stops at $1,000 combined model spend (watcher below) and reports.
set -u
cd ~/h2; echo "a8668fc6641bc9eeb855065688fbbc02a0d3754c0021013e5169b4b0b0b88814  hard-suite-prereg-v2.md" | sha256sum -c || exit 9
R=$HOME/h2/h2-hardsuite-1022; mkdir -p $R
# The agent container is unmodified h1-env:1022. Checker venvs are a separate
# image (h2-checker-venvs), extracted to a directory and mounted at
# /h2/checker-venvs — not at /opt/h2-checker-venvs. The runner copies that
# tree into a cell-private directory only after the agent phase.
AGENT_IMAGE=h1-env:1022
AGENT_DIGEST=$(sudo docker image inspect -f '{{.Id}}' "$AGENT_IMAGE")
STAGE=$HOME/h2/checker-venvs
if [ ! -d "$STAGE/torch-tensor-parallelism" ]; then
  cid=$(sudo docker create h2-checker-venvs:latest /bin/true)
  rm -rf "$STAGE"
  sudo docker cp "$cid":/opt/h2-checker-venvs "$STAGE"
  sudo docker rm "$cid" >/dev/null
fi
# Spend-monitor self-test on a known-nonzero fixture (#198 gate cells, $0.3708).
# A spend stop only counts once this passes; abort the launch otherwise.
python3 ~/ob/thesis/ab/h2env/spend_monitor.py --self-test || { echo "spend monitor self-test failed; not launching" >&2; exit 8; }
set +e
sudo docker run --rm --network none --entrypoint python3 "$AGENT_IMAGE" -c 'import torch' >/tmp/h1-torch.out 2>/tmp/h1-torch.err
h1rc=$?
set -u
H1_TORCH_PROBE=$(PYTHONPATH=$HOME/ob python3 -c 'from obench.checker_venv import normalize_torch_probe; import pathlib; print(normalize_torch_probe('"$h1rc"', pathlib.Path("/tmp/h1-torch.err").read_text()))')
echo "$(TZ=America/New_York date '+%F %T %Z') start H2 vm=n2-standard-16 runner=$(git -C ~/ob rev-parse HEAD) agent_image=$AGENT_IMAGE($AGENT_DIGEST) checker_venvs=h2-checker-venvs prereg_sha=a8668fc6 controls=2533,913,11731 jobs=4/model seed=1022" >> $R/driver.log
( while true; do echo "$(TZ=America/New_York date '+%F %T %Z') $(cat /proc/loadavg) memfree_mb=$(free -m | awk '/Mem/{print $7}') disk_free=$(df -BG --output=avail / | tail -1)" >> $R/load.log; sleep 300; done ) & LP=$!
run() { sudo docker run -d --name h2-$1 --network host -e OBENCH_ADC_METADATA=1 -e GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d -e VERTEX_LOCATION=global -e OBENCH_VM_TYPE=n2-standard-16 -e OBENCH_AGENT_IMAGE=$AGENT_IMAGE -e OBENCH_AGENT_IMAGE_DIGEST=$AGENT_DIGEST -e OBENCH_CHECKER_VENV_STAGE=/h2/checker-venvs -e OBENCH_H1_TORCH_PROBE="$H1_TORCH_PROBE" -e TZ=America/New_York -v $HOME/ob:/ob -v $HOME/h1:/h1 -v $HOME/h2:/h2 -v $STAGE:/h2/checker-venvs:ro $AGENT_IMAGE /h2/run1-h1env.sh claude-$1-5-5 /h2/h2-hardsuite-1022/$1 $2 1000 4; }
run sonnet 3052,13331,26821,1109,795,2533,913,11731
run opus 3052,13331,26821,13090,5140,913,4204
# spend + disk watcher: combined model cost from cell records; stop both at >= $990 or disk < 15 GB
( while sudo docker ps -q -f name=h2- | grep -q .; do
    C=$(python3 ~/ob/thesis/ab/h2env/spend_monitor.py "$R" | sed -n 's/^spend=\([0-9.]*\).*/\1/p')
    F=$(df -BG --output=avail / | tail -1 | tr -dc 0-9)
    echo "$(TZ=America/New_York date '+%F %T %Z') spend=\$$C free=${F}G cells=$(find $R -path '*/cells/*' -name '*.json' 2>/dev/null | wc -l)" >> $R/spend.log
    if python3 -c "import sys;sys.exit(0 if $C>=985 else 1)"; then echo "STOP spend $C" > $R/STOPPED; sudo docker stop -t 30 h2-sonnet h2-opus; fi
    if [ $F -lt 15 ]; then echo "STOP disk ${F}G" > $R/STOPPED; sudo docker stop -t 30 h2-sonnet h2-opus; fi
    sleep 60; done ) & WP=$!
sudo docker wait h2-sonnet h2-opus >> $R/driver.log
kill $LP; wait $WP; echo "$(TZ=America/New_York date '+%F %T %Z') end H2 $(cat $R/STOPPED 2>/dev/null)" >> $R/driver.log
