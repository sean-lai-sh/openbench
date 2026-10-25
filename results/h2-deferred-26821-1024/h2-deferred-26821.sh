#!/bin/bash
# Opus 26821 rerun, fresh dir, 90 cells/side, hard $150 stop. Prior 32/side partial kept in h2-deferred-1023/opus/26821.
set -u
R=$HOME/h2/h2-deferred-26821-1024; mkdir -p $R
echo "$(TZ=America/New_York date "+%F %T %Z") start opus26821 rerun runner=$(git -C ~/ob rev-parse HEAD) image=h2-env:1022 jobs=4 seed=1022 cap=150" >> $R/driver.log
sudo docker run -d --name h2r-opus26821 --network host -e OBENCH_ADC_METADATA=1 -e GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d -e VERTEX_LOCATION=global -e OBENCH_VM_TYPE=n2-standard-16 -e TZ=America/New_York -v $HOME/ob:/ob -v $HOME/h1:/h1 -v $HOME/h2:/h2 h2-env:1022 /h2/run1.sh claude-opus-5-5 /h2/h2-deferred-26821-1024/opus 26821 150 4 >> $R/driver.log
( while sudo docker ps -q -f name=h2r-opus26821 | grep -q .; do
    C=$(python3 -c "import json,glob;print(round(sum((json.load(open(f)).get(\"requests_cost_usd\") or 0) for f in glob.glob(\"$R/*/*/cells/*/*/*.json\")),2))")
    F=$(df -BG --output=avail / | tail -1 | tr -dc 0-9)
    echo "$(TZ=America/New_York date "+%F %T %Z") spend=\$$C free=${F}G cells=$(ls $R/*/*/cells/*/*/*.json 2>/dev/null | wc -l)" >> $R/spend.log
    if python3 -c "import sys;sys.exit(0 if $C>=148 else 1)"; then echo "STOP spend $C" > $R/STOPPED; sudo docker stop -t 30 h2r-opus26821; fi
    if [ ${F:-0} -lt 15 ]; then echo "STOP disk ${F}G" > $R/STOPPED; sudo docker stop -t 30 h2r-opus26821; fi
    sleep 60; done ) 
echo "$(TZ=America/New_York date "+%F %T %Z") end $(sudo docker inspect -f '{{.State.ExitCode}}' h2r-opus26821) $(cat $R/STOPPED 2>/dev/null)" >> $R/driver.log
