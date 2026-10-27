#!/bin/bash
# Step-8 F03-2 launcher (rev. 2026-10-27, PR #166). NOT launched by this PR.
# Image h1-env:1027-strace (h1-env:1022 + strace 6.1); tag recorded on every cell.
# Per side: 1 traced gate cell (OBENCH_PROVIDER_TRACE=1, unscored, kept as infra
# evidence) + 30 untraced scored cells (OBENCH_PROVIDER_TRACE=0). Scored cells
# record opencode_cache + lockfile_sha256 + cell_image + provider_trace.
# Gate (thesis.ab.step8_gate): loaded provider == pin, by probe_method strace or
# embedded (bundled provider read from the binary). >2 mismatched sides -> STOP.
# Hard stop $60 batch spend (flag file at $50).
# Usage: RUNNER_SHA=<openbench sha checked out in ~/ob-f032> bash step8_f032.sh
set -u
B=$HOME/s8f032run; mkdir -p $B
IMG=h1-env:1027-strace
PRS=3251,3302,3381,3390,3402,3424,3433,3449,3481,3507,3546
log(){ echo "$(TZ=America/New_York date '+%F %T %Z') $*" >> $B/driver.log; }
spend(){ python3 -c "import json,glob;print(round(sum((json.load(open(f)).get('requests_cost_usd') or 0) for f in glob.glob('$B/[gs]*/*/cells/*/*/*.json')),2))"; }
[ "$(git -C ~/ob-f032 rev-parse HEAD)" = "${RUNNER_SHA:?set RUNNER_SHA}" ] || { log "runner not $RUNNER_SHA; abort"; exit 1; }
sudo docker image inspect $IMG >/dev/null || { log "image $IMG missing; abort"; exit 1; }
# 3481 runs only with OPENCODE_CHANNEL=local builds on both sides (Researcher ruling).
for s in 51e4c9fc4cb4ef01f7d337127b463729c2967594 c1ada302f983f150ec42c473d316b3488318163b; do
  grep -q '"build_channel": "local"' ~/s8f032/bin/$s/build-stamp.json 2>/dev/null || { PRS=${PRS/3481,/}; log "3481 excluded: side $s not a local-channel build"; break; }
done
run(){ # $1 out-name $2 prs $3 trials $4 cap $5 trace(1|0)
  sudo docker rm -f s8-f032 >/dev/null 2>&1
  sudo docker run -d --name s8-f032 --network host -e OBENCH_ADC_METADATA=1 -e GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d -e VERTEX_LOCATION=global -e OBENCH_VM_TYPE=n2-standard-16 -e OBENCH_CELL_IMAGE=$IMG -e OBENCH_PROVIDER_TRACE=$5 -e TZ=America/New_York -e PATH=/h1/opencode-src/go/1.24.6/bin:/h1/toolchain/node-v20.19.2-linux-x64/bin:/root/.local/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin -v $HOME/ob-f032:/ob -v $HOME/h1:/h1 -v $HOME/s8f032:/c -v $HOME/s8:/s8 -v $B:/o $IMG bash -c "
git config --global --add safe.directory '*'; python3 -m venv /venv && /venv/bin/pip install -q -e /ob && cd /ob && exec /venv/bin/python -m thesis.ab.run_ab /s8/prs.csv --pr $2 --task-map /s8/task-map.csv --trials $3 --jobs 4 --vertex-model claude-sonnet-5-5 --cell-meta --out /o/$1 --cache /c --order interleave-seeded --seed 1016 --max-cost-usd $4 > /o/$1.log 2>&1" >/dev/null
  while sudo docker ps -q -f name=s8-f032 | grep -q .; do
    V=$(spend); echo "$(TZ=America/New_York date '+%F %T %Z') $1 spend=\$$V" >> $B/spend.log
    python3 -c "import sys;sys.exit(0 if $V>=50 else 1)" && [ ! -e $B/FLAG-50 ] && { echo "spend \$$V >= \$50" > $B/FLAG-50; log "FLAG: $(cat $B/FLAG-50)"; }
    python3 -c "import sys;sys.exit(0 if $V>=60 else 1)" && { echo "hard stop: spend \$$V >= \$60" > $B/STOP; log "$(cat $B/STOP)"; sudo docker stop -t 60 s8-f032; }
    sleep 30; done
  log "end $1 rc=$(sudo docker inspect -f '{{.State.ExitCode}}' s8-f032) spend=\$$(spend)"
}
log "start gate (1 traced unscored cell per side) prs=$PRS image=$IMG"
run gate $PRS 1 60 1
[ -e $B/STOP ] && exit 1
(cd ~/ob-f032 && python3 -m thesis.ab.step8_gate $B/gate thesis/ab/provider_pins.json ~/s8/prs_f032_sides.json) > $B/gate.json; rc=$?
log "gate rc=$rc $(python3 -c "import json;d=json.load(open('$B/gate.json'));print('ok_prs',d['ok_prs'],'mismatch',d['mismatch_sides'])")"
[ $rc -ne 0 ] && { echo "gate: >2 sides mismatched (see gate.json)" > $B/STOP; log "$(cat $B/STOP)"; exit 1; }
touch $B/GATE-DONE  # gate cells are infra evidence; scoring reads only $B/scored
P=$(python3 -c "import json;d=json.load(open('$B/gate.json'));c=[x['cost'] or 0 for x in d['cells'] if x['pr'] in d['ok_prs']];print(round(sum(c)*30,2))")
python3 -c "import sys;sys.exit(0 if $P+$(spend)>60 else 1)" && { echo "projected \$$(python3 -c "print(round($P+$(spend),2))") > \$60; holding before scored phase" > $B/HOLD; log "$(cat $B/HOLD)"; exit 0; }
OK=$(python3 -c "import json;print(','.join(json.load(open('$B/gate.json'))['ok_prs']))")
[ -z "$OK" ] && { log "no PRs passed gate"; exit 1; }
CAP=$(python3 -c "print(round(60-$(spend),2))")
log "start scored prs=$OK trials=30 untraced cap=\$$CAP"
run scored $OK 30 $CAP 0
[ -e $B/STOP ] || touch $B/DONE
log "F03-2 done spend=\$$(spend)"
