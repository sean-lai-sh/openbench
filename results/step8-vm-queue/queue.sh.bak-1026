#!/bin/bash
# Step-8 VM queue (M1 + D1). Runner 980e71b6 (~/ob-s8), image h1-env:1022, Sonnet 5.5, 30/side, jobs 4,
# --order interleave-seeded --seed 1016, --task-map, --cell-meta (host/vm_type/runner_commit per cell).
# Sub-invocations from SUBS.txt in order. Stops: step-8 cap $5050 total (box spend $198.47 + VM), HOLD at VM spend >= $1320
# go 1.24.6 (runner cache) + node v20.19.2 (same as box) on PATH for builds/tasks; box used host go 1.24.4, npm 9.2.0.
# (20% over the ~$1100 VM estimate), disk free < 20G, QUEUE-STOP/HOLD files.
set -u
B=$HOME/s8; RUN=$B/runs; mkdir -p $RUN
log(){ echo "$(TZ=America/New_York date '+%F %T %Z') $*" >> $B/driver.log; }
spend(){ python3 -c "import json,glob;print(round(sum((json.load(open(f)).get('requests_cost_usd') or 0) for f in glob.glob('$RUN/*/*/cells/*/*/*.json')),2))"; }
[ "$(git -C ~/ob-s8 rev-parse HEAD | cut -c1-8)" = 980e71b6 ] || { log "runner not 980e71b6; abort"; exit 1; }
while read lab prs; do
  [ -z "$lab" ] && continue; [ -e $B/DONE-$lab ] && continue
  [ -e $B/QUEUE-STOP ] && { log "stopped: $(cat $B/QUEUE-STOP)"; exit 1; }; [ -e $B/HOLD ] && { log "hold: $(cat $B/HOLD)"; exit 0; }
  F=$(df -BG --output=avail / | tail -1 | tr -dc 0-9); [ $F -lt 20 ] && { echo "disk free ${F}G < 20G before $lab" > $B/QUEUE-STOP; log "$(cat $B/QUEUE-STOP)"; exit 1; }
  V=$(spend); CAP=$(python3 -c "print(round(5050-198.47-$V,2))")
  python3 -c "import sys;sys.exit(0 if $V>=1320 else 1)" && { echo "VM spend \$$V >= \$1320 (20% overrun of ~\$1100 est)" > $B/HOLD; log "$(cat $B/HOLD)"; exit 0; }
  ls ~/h1/opencode-src/worktrees > $B/wt-before-$lab.txt
  O=$RUN/$lab; mkdir -p $O; sudo docker rm -f s8-run >/dev/null 2>&1
  log "start $lab $prs trials=30 runner=$(git -C ~/ob-s8 rev-parse --short=10 HEAD) vm_spend=\$$V cap=\$$CAP free=${F}G"
  sudo docker run -d --name s8-run --network host -e OBENCH_ADC_METADATA=1 -e GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d -e VERTEX_LOCATION=global -e OBENCH_VM_TYPE=n2-standard-16 -e TZ=America/New_York -e PATH=/h1/opencode-src/go/1.24.6/bin:/h1/toolchain/node-v20.19.2-linux-x64/bin:/root/.local/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin -v $HOME/ob-s8:/ob -v $HOME/h1:/h1 -v $B:/s8 h1-env:1022 bash -c "
git config --global --add safe.directory '*'; python3 -m venv /venv && /venv/bin/pip install -q -e /ob && cd /ob && exec /venv/bin/python -m thesis.ab.run_ab /s8/prs.csv --pr $prs --task-map /s8/task-map.csv --trials 30 --jobs 4 --vertex-model claude-sonnet-5-5 --cell-meta --out /s8/runs/$lab --cache /h1/opencode-src --order interleave-seeded --seed 1016 --max-cost-usd $CAP > /s8/runs/$lab/$lab.log 2>&1" >/dev/null
  while sudo docker ps -q -f name=s8-run | grep -q .; do
    F=$(df -BG --output=avail / | tail -1 | tr -dc 0-9); V=$(spend)
    echo "$(TZ=America/New_York date '+%F %T %Z') $lab vm_spend=\$$V cells=$(ls $RUN/*/*/cells/*/*/*.json 2>/dev/null | wc -l) free=${F}G" >> $B/spend.log
    [ $F -lt 15 ] && { echo "disk free ${F}G < 15G during $lab" > $B/QUEUE-STOP; sudo docker stop -t 60 s8-run; }
    python3 -c "import sys;sys.exit(0 if $V>=5050-198.47 else 1)" && { echo "step-8 cap \$5050 reached" > $B/QUEUE-STOP; sudo docker stop -t 60 s8-run; }
    sleep 60; done
  rc=$(sudo docker inspect -f '{{.State.ExitCode}}' s8-run)
  log "end $lab rc=$rc vm_spend=\$$(spend) free=$(df -BG --output=avail / | tail -1 | tr -dc 0-9)G"
  # free disk: remove worktrees this sub-invocation created, via git inside the container (paths are /h1/...)
  NEW=$(comm -13 $B/wt-before-$lab.txt <(ls ~/h1/opencode-src/worktrees) | tr '\n' ' ')
  [ -n "$NEW" ] && sudo docker run --rm -v $HOME/h1:/h1 h1-env:1022 bash -c "git config --global --add safe.directory '*'; for w in $NEW; do git -C /h1/opencode-src/mirror worktree remove --force /h1/opencode-src/worktrees/\$w || rm -rf /h1/opencode-src/worktrees/\$w; done; git -C /h1/opencode-src/mirror worktree prune" >> $B/cleanup.log 2>&1
  N=$(ls $O/*/cells/*/*/*.json 2>/dev/null | wc -l); [ "$N" -gt 0 ] || { echo "$lab produced 0 cells (rc=$rc)" > $B/QUEUE-STOP; }
  [ "$rc" = 0 ] && [ ! -e $B/QUEUE-STOP ] && touch $B/DONE-$lab || { [ -e $B/QUEUE-STOP ] || echo "$lab rc=$rc" > $B/QUEUE-STOP; log "stopped after $lab: $(cat $B/QUEUE-STOP)"; exit 1; }
done < $B/SUBS.txt
log "all VM sub-batches complete"
