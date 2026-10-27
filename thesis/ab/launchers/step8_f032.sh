#!/bin/bash
# Step-8 F03-2 launcher (rev. 2026-10-27, PR #166). NOT launched by this PR.
# Image h1-env:1027-strace (h1-env:1022 + strace 6.1); tag recorded on every cell.
# Per side: 1 traced gate cell (OBENCH_PROVIDER_TRACE=1, unscored, kept as infra
# evidence) + 30 untraced scored cells (OBENCH_PROVIDER_TRACE=0). Scored cells
# record opencode_cache + lockfile_sha256 + cell_image + provider_trace.
# Gate (thesis.ab.step8_gate): loaded provider == pin, by probe_method strace or
# embedded (bundled provider read from the binary). >2 mismatched sides -> STOP.
# Hard stop $60 batch spend (flag file at $50).
# Route (thesis.ab.route): compat sets the proxy base URL on BOTH routes
# (config options.baseURL and ANTHROPIC_BASE_URL); every cell logs `route`
# (on:/off:<how>). Off-route cells are infra (not scored, listed for rerun);
# >2 off-route on a side halts the side, >2 halted sides halts the batch.
# Egress backstop (egress_block.sh): api.anthropic.com REJECTed in host OUTPUT
# for the whole run + container /etc/hosts sinkhole; verified failing before
# any cell runs; re-resolved (A+AAAA) every 30 s with a REJECT added for any
# new IP (failure to add = abort); removed on exit.
# Halt: OBENCH_ROUTE_HALT=1 makes run_ab stop launching a side's cells as soon
# as it has >2 off-route cells; spend by cells started after the halt is in
# route-<phase>.json halted_spend.
# Reruns: RERUN=1 runs route-scored.json's rerun list into $B/rerun tagged
# rerun=1 (manual reruns must set OBENCH_RERUN=1 too); same route check.
# complete.json (step8_gate --complete) lists sides with 30 on-route scored
# cells; the rest are incomplete and are not scored or padded.
# Usage: RUNNER_SHA=<openbench sha checked out in ~/ob-f032> bash step8_f032.sh
set -u
B=$HOME/s8f032run; mkdir -p $B
IMG=h1-env:1027-strace
PRS=3251,3302,3381,3390,3402,3424,3433,3449,3481,3507,3546
log(){ echo "$(TZ=America/New_York date '+%F %T %Z') $*" >> $B/driver.log; }
spend(){ python3 -c "import json,glob;print(round(sum((json.load(open(f)).get('requests_cost_usd') or 0) for f in glob.glob('$B/[gsr]*/*/cells/*/*/*.json')),2))"; }
. ~/ob-f032/thesis/ab/launchers/egress_block.sh
[ "$(git -C ~/ob-f032 rev-parse HEAD)" = "${RUNNER_SHA:?set RUNNER_SHA}" ] || { log "runner not $RUNNER_SHA; abort"; exit 1; }
sudo docker image inspect $IMG >/dev/null || { log "image $IMG missing; abort"; exit 1; }
trap 'egress_remove >> $B/driver.log 2>&1' EXIT
egress_apply >> $B/driver.log 2>&1 || { log "egress block apply failed; abort"; exit 1; }
egress_verify $IMG > $B/egress_verify.txt 2>&1 || { log "egress verify: api.anthropic.com reachable; abort"; exit 1; }
log "egress verified blocked: $(tr '\n' ' ' < $B/egress_verify.txt)"
# 3481 runs only with OPENCODE_CHANNEL=local builds on both sides (Researcher ruling).
for s in 51e4c9fc4cb4ef01f7d337127b463729c2967594 c1ada302f983f150ec42c473d316b3488318163b; do
  grep -q '"build_channel": "local"' ~/s8f032/bin/$s/build-stamp.json 2>/dev/null || { PRS=${PRS/3481,/}; log "3481 excluded: side $s not a local-channel build"; break; }
done
route(){ # off-route check over $B/$1; rc 1 = halt batch
  [ -d $B/$1 ] || return 0
  (cd ~/ob-f032 && python3 -m thesis.ab.step8_gate --route $B/$1) > $B/route-$1.json; local rc=$?
  python3 -c "import json;d=json.load(open('$B/route-$1.json'));open('$B/HALT-SIDES-$1','w').write('\n'.join(d['halted_sides'])+'\n') if d['halted_sides'] else None"
  return $rc
}
run(){ # $1 out-name $2 prs $3 trials $4 cap $5 trace(1|0) $6 extra docker -e args
  sudo docker rm -f s8-f032 >/dev/null 2>&1
  sudo docker run -d --name s8-f032 --network host $EGRESS_ADD_HOST -e OBENCH_ADC_METADATA=1 -e GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d -e VERTEX_LOCATION=global -e OBENCH_VM_TYPE=n2-standard-16 -e OBENCH_CELL_IMAGE=$IMG -e OBENCH_PROVIDER_TRACE=$5 -e OBENCH_ROUTE_HALT=1 ${6:-} -e TZ=America/New_York -e PATH=/h1/opencode-src/go/1.24.6/bin:/h1/toolchain/node-v20.19.2-linux-x64/bin:/root/.local/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin -v $HOME/ob-f032:/ob -v $HOME/h1:/h1 -v $HOME/s8f032:/c -v $HOME/s8:/s8 -v $B:/o $IMG bash -c "
git config --global --add safe.directory '*'; python3 -m venv /venv && /venv/bin/pip install -q -e /ob && cd /ob && exec /venv/bin/python -m thesis.ab.run_ab /s8/prs.csv --pr $2 --task-map /s8/task-map.csv --trials $3 --jobs 4 --vertex-model claude-sonnet-5-5 --cell-meta --out /o/$1 --cache /c --order interleave-seeded --seed 1016 --max-cost-usd $4 > /o/$1.log 2>&1" >/dev/null
  while sudo docker ps -q -f name=s8-f032 | grep -q .; do
    V=$(spend); echo "$(TZ=America/New_York date '+%F %T %Z') $1 spend=\$$V" >> $B/spend.log
    python3 -c "import sys;sys.exit(0 if $V>=50 else 1)" && [ ! -e $B/FLAG-50 ] && { echo "spend \$$V >= \$50" > $B/FLAG-50; log "FLAG: $(cat $B/FLAG-50)"; }
    python3 -c "import sys;sys.exit(0 if $V>=60 else 1)" && { echo "hard stop: spend \$$V >= \$60" > $B/STOP; log "$(cat $B/STOP)"; sudo docker stop -t 60 s8-f032; }
    egress_refresh >> $B/egress_refresh.log 2>&1 || { echo "egress: could not block a new api.anthropic.com IP" > $B/STOP; log "$(cat $B/STOP)"; sudo docker stop -t 60 s8-f032; break; }
    route $1 || { echo "route: >2 sides halted off-route in $1 (see $B/route-$1.json)" > $B/STOP; log "$(cat $B/STOP)"; sudo docker stop -t 60 s8-f032; }
    sleep 30; done
  log "end $1 rc=$(sudo docker inspect -f '{{.State.ExitCode}}' s8-f032) spend=\$$(spend)"
}
log "start gate (1 traced unscored cell per side) prs=$PRS image=$IMG"
run gate $PRS 1 60 1
[ -e $B/STOP ] && exit 1
(cd ~/ob-f032 && python3 -m thesis.ab.step8_gate $B/gate thesis/ab/provider_pins.json ~/s8/prs_f032_sides.json) > $B/gate.json; rc=$?
log "gate rc=$rc $(python3 -c "import json;d=json.load(open('$B/gate.json'));print('ok_prs',d['ok_prs'],'mismatch',d['mismatch_sides'])")"
[ $rc -ne 0 ] && { echo "gate: >2 sides mismatched (see gate.json)" > $B/STOP; log "$(cat $B/STOP)"; exit 1; }
route gate; log "gate route: $(python3 -c "import json;d=json.load(open('$B/route-gate.json'));print('off_route',sorted(d['off_route']),'halted',d['halted_sides'])")"
touch $B/GATE-DONE  # gate cells are infra evidence; scoring reads only $B/scored
P=$(python3 -c "import json;d=json.load(open('$B/gate.json'));c=[x['cost'] or 0 for x in d['cells'] if x['pr'] in d['ok_prs']];print(round(sum(c)*30,2))")
python3 -c "import sys;sys.exit(0 if $P+$(spend)>60 else 1)" && { echo "projected \$$(python3 -c "print(round($P+$(spend),2))") > \$60; holding before scored phase" > $B/HOLD; log "$(cat $B/HOLD)"; exit 0; }
OK=$(python3 -c "import json;print(','.join(json.load(open('$B/gate.json'))['ok_prs']))")
[ -z "$OK" ] && { log "no PRs passed gate"; exit 1; }
CAP=$(python3 -c "print(round(60-$(spend),2))")
log "start scored prs=$OK trials=30 untraced cap=\$$CAP"
run scored $OK 30 $CAP 0
route scored; log "scored route: $(python3 -c "import json;d=json.load(open('$B/route-scored.json'));print('rerun(infra:off_route)',len(d['rerun']),'halted',d['halted_sides'])")"
if [ "${RERUN:-0}" = 1 ] && [ ! -e $B/STOP ] && python3 -c "import json,sys;sys.exit(0 if json.load(open('$B/route-scored.json'))['rerun'] else 1)"; then
  CAP=$(python3 -c "print(round(60-$(spend),2))")
  log "start rerun of off-route cells (tagged rerun=1) cap=\$$CAP"
  run rerun $OK 30 $CAP 0 "-e OBENCH_RERUN=1 -e OBENCH_RERUN_CELLS=/o/route-scored.json"
  route rerun
fi
(cd ~/ob-f032 && python3 -m thesis.ab.step8_gate --complete $B/scored $B/gate.json $( [ -d $B/rerun ] && echo $B/rerun )) > $B/complete.json
log "complete sides: $(python3 -c "import json;d=json.load(open('$B/complete.json'));print(len(d['complete']),'incomplete',sorted(d['incomplete']))")"
[ -e $B/STOP ] || touch $B/DONE
log "F03-2 done spend=\$$(spend)"
