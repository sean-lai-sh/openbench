#!/bin/bash
# H2 driver (VM host). Pre-reg v2 + A1 + A2, sha256 a8668fc6641bc9eeb855065688fbbc02a0d3754c0021013e5169b4b0b0b88814
# Sean approved via PM 2026-10-22 (hard-suite cap $5K); executor stops at $1,000 combined model spend (watcher below) and reports.
set -u
# --- launch guard (added 2026-10-30, after the 1022 run; lines below it are the as-ran record, unchanged) ---
# The 1022 run used the inline python spend sum in the watcher below. A NEW paid launch from this
# file must first pass spend_monitor.py --self-test and must run on the exact h2-env:1022 image.
H2_IMAGE_DIGEST=sha256:72c59033194aae26f6de67c62c77d742aef1d71849000e308f3ee875ff5169ff
python3 ~/ob/thesis/ab/h2env/spend_monitor.py --self-test || { echo "REFUSE: spend_monitor.py --self-test failed" >&2; exit 8; }
H2_IMAGE_GOT=$(sudo docker image inspect -f '{{.Id}}' h2-env:1022 2>/dev/null)
[ "$H2_IMAGE_GOT" = "$H2_IMAGE_DIGEST" ] || { echo "REFUSE: h2-env:1022 is '${H2_IMAGE_GOT:-missing}', want $H2_IMAGE_DIGEST" >&2; exit 8; }
# --- end launch guard ---
cd ~/h2; echo "a8668fc6641bc9eeb855065688fbbc02a0d3754c0021013e5169b4b0b0b88814  hard-suite-prereg-v2.md" | sha256sum -c || exit 9
R=$HOME/h2/h2-hardsuite-1022; mkdir -p $R
echo "$(TZ=America/New_York date '+%F %T %Z') start H2 vm=n2-standard-16 runner=$(git -C ~/ob rev-parse HEAD) image=h2-env:1022($(sudo docker image inspect -f '{{.Id}}' h2-env:1022)) prereg_sha=a8668fc6 controls=2533,913,11731 jobs=4/model seed=1022" >> $R/driver.log
( while true; do echo "$(TZ=America/New_York date '+%F %T %Z') $(cat /proc/loadavg) memfree_mb=$(free -m | awk '/Mem/{print $7}') disk_free=$(df -BG --output=avail / | tail -1)" >> $R/load.log; sleep 300; done ) & LP=$!
run() { sudo docker run -d --name h2-$1 --network host -e OBENCH_ADC_METADATA=1 -e GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d -e VERTEX_LOCATION=global -e OBENCH_VM_TYPE=n2-standard-16 -e OBENCH_AGENT_IMAGE=h2-env:1022 -e OBENCH_AGENT_IMAGE_DIGEST=$(sudo docker image inspect -f "{{.Id}}" h2-env:1022) -e TZ=America/New_York -v $HOME/ob:/ob -v $HOME/h1:/h1 -v $HOME/h2:/h2 h2-env:1022 /h2/run1.sh claude-$1-5-5 /h2/h2-hardsuite-1022/$1 $2 1000 4; }
run sonnet 3052,13331,26821,1109,795,2533,913,11731
run opus 3052,13331,26821,13090,5140,913,4204
# spend + disk watcher: combined model cost from cell records; stop both at >= $990 or disk < 15 GB
( while sudo docker ps -q -f name=h2- | grep -q .; do
    C=$(python3 -c "import json,glob;print(round(sum((json.load(open(f)).get('requests_cost_usd') or 0) for f in glob.glob('$R/*/*/cells/*/*/*.json')),2))")
    F=$(df -BG --output=avail / | tail -1 | tr -dc 0-9)
    echo "$(TZ=America/New_York date '+%F %T %Z') spend=\$$C free=${F}G cells=$(ls $R/*/*/cells/*/*/*.json 2>/dev/null | wc -l)" >> $R/spend.log
    if python3 -c "import sys;sys.exit(0 if $C>=985 else 1)"; then echo "STOP spend $C" > $R/STOPPED; sudo docker stop -t 30 h2-sonnet h2-opus; fi
    if [ $F -lt 15 ]; then echo "STOP disk ${F}G" > $R/STOPPED; sudo docker stop -t 30 h2-sonnet h2-opus; fi
    sleep 60; done ) & WP=$!
sudo docker wait h2-sonnet h2-opus >> $R/driver.log
kill $LP; wait $WP; echo "$(TZ=America/New_York date '+%F %T %Z') end H2 $(cat $R/STOPPED 2>/dev/null)" >> $R/driver.log
