#!/bin/bash
# H1 driver (VM host). Pre-reg v2 + Amendment A1, sha256 c37a442252916d172f403f27acd421b1a052d479d1bb36db6388c2e0e9697902
R=$HOME/h1/h1-hardprobe-1022; mkdir -p $R
T=dna-insert,filter-js-from-html,model-extraction-relu-logits,polyglot-rust-c,regex-chess,sam-cell-seg,torch-pipeline-parallelism,torch-tensor-parallelism,video-processing
echo "$(TZ=America/New_York date '+%F %T %Z') start H1 vm=n2-standard-16 runner=$(git -C ~/ob rev-parse HEAD) opencode=c10134729d prereg_sha=c37a4422 jobs=3/model" >> $R/driver.log
( while true; do echo "$(TZ=America/New_York date '+%F %T %Z') $(cat /proc/loadavg) memfree_mb=$(free -m | awk '/Mem/{print $7}') disk_free=$(df -BG --output=avail / | tail -1)" >> $R/load.log; sleep 300; done ) & LP=$!
for M in sonnet opus; do
  sudo docker run -d --name h1-$M --network host -e OBENCH_ADC_METADATA=1 -e GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d -e VERTEX_LOCATION=global -e OBENCH_VM_TYPE=n2-standard-16 -e TZ=America/New_York -v $HOME/ob:/ob -v $HOME/h1:/h1 h1-env:1022 /h1/run1.sh claude-$M-5-5 /h1/h1-hardprobe-1022/$M $T 75 3
done
sudo docker wait h1-sonnet h1-opus >> $R/driver.log
kill $LP; echo "$(TZ=America/New_York date '+%F %T %Z') end H1" >> $R/driver.log
