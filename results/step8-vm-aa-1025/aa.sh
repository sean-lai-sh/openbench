#!/bin/bash
# Step-8 M1 VM A/A: stock OpenCode 4643e13 (PR 26821 parent) vs itself, trig-todo-task, Sonnet 5.5, 30/side, seed 1016, cap $20.
set -u
R=$HOME/s8aa/step8-vm-aa-1025; mkdir -p $R
echo "$(TZ=America/New_York date '+%F %T %Z') start runner=$(git -C ~/ob-s8 rev-parse HEAD) image=h1-env:1022 vm=n2-standard-16 jobs=4 seed=1016 cap=20" >> $R/driver.log
sudo docker run -d --name s8-aa --network host -e OBENCH_ADC_METADATA=1 -e GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d -e VERTEX_LOCATION=global -e OBENCH_VM_TYPE=n2-standard-16 -e TZ=America/New_York -v $HOME/ob-s8:/ob -v $HOME/h1:/h1 -v $HOME/s8aa:/s8aa h1-env:1022 bash -c '
git config --global --add safe.directory "*"; python3 -m venv /venv && /venv/bin/pip install -q -e /ob && cd /ob && exec /venv/bin/python -m thesis.ab.run_ab /ob/thesis/ab/fixtures/opencode-harness-prs.csv --pr 26821 --task trig-todo-task --aa --trials 30 --jobs 4 --vertex-model claude-sonnet-5-5 --cell-meta --out /s8aa/step8-vm-aa-1025/run --cache /h1/opencode-src --order interleave-seeded --seed 1016 --max-cost-usd 20 > /s8aa/step8-vm-aa-1025/run.log 2>&1' >> $R/driver.log
while sudo docker ps -q -f name=s8-aa | grep -q .; do
  C=$(python3 -c "import json,glob;print(round(sum((json.load(open(f)).get('requests_cost_usd') or 0) for f in glob.glob('$R/run/*/cells/*/*/*.json')),2))")
  echo "$(TZ=America/New_York date '+%F %T %Z') spend=\$$C cells=$(ls $R/run/*/cells/*/*/*.json 2>/dev/null | wc -l)" >> $R/spend.log
  python3 -c "import sys;sys.exit(0 if $C>=19.5 else 1)" && { echo "STOP spend $C" > $R/STOPPED; sudo docker stop -t 30 s8-aa; }
  sleep 60; done
echo "$(TZ=America/New_York date '+%F %T %Z') end rc=$(sudo docker inspect -f '{{.State.ExitCode}}' s8-aa)" >> $R/driver.log
