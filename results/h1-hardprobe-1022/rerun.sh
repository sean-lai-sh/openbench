#!/bin/bash
# Env-failure reruns: checker cold `uvx` install of torch 2.7.0 took 126 s > 120 s checker cap (env failure, unscored).
# Fix: prewarmed shared UV_CACHE_DIR=/h1/uvcache (warm uvx 0.6 s). Original cells kept, marked env_failure in ENV-FAILURES.txt.
R=$HOME/h1/h1-hardprobe-1022
sudo docker run --rm --network host -e UV_CACHE_DIR=/h1/uvcache -v $HOME/h1:/h1 h1-env:1022 bash -c "cd /tmp && uvx -p 3.13 -w pytest==8.4.1 -w torch==2.7.0 -w pytest-json-ctrf==0.3.5 pytest --version"
echo "$(TZ=America/New_York date '+%F %T %Z') start reruns (UV_CACHE_DIR prewarmed)" >> $R/driver.log
( while true; do echo "$(TZ=America/New_York date '+%F %T %Z') $(cat /proc/loadavg) memfree_mb=$(free -m | awk '/Mem/{print $7}') disk_free=$(df -BG --output=avail / | tail -1)" >> $R/load.log; sleep 300; done ) & LP=$!
run() { sudo docker run -d --name h1r-$1 --network host -e UV_CACHE_DIR=/h1/uvcache -e OBENCH_ADC_METADATA=1 -e GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d -e VERTEX_LOCATION=global -e OBENCH_VM_TYPE=n2-standard-16 -e TZ=America/New_York -v $HOME/ob:/ob -v $HOME/h1:/h1 h1-env:1022 /h1/run1.sh claude-$1-5-5 /h1/h1-hardprobe-1022/$1-rerun $2 $3 3; }
run sonnet torch-pipeline-parallelism 20
run opus torch-pipeline-parallelism,torch-tensor-parallelism 40
sudo docker wait h1r-sonnet h1r-opus >> $R/driver.log
kill $LP; echo "$(TZ=America/New_York date '+%F %T %Z') end reruns" >> $R/driver.log
