#!/bin/bash
# #191 regate at b43e88d1c3: Opus 4204 torch-tensor-parallelism t1 both sides, original binaries, $5 stop
set -u
R=$HOME/gate191b; mkdir -p $R/h2
log(){ echo "$(TZ=America/New_York date '+%F %T %Z') $*" >> $R/driver.log; }
while pgrep -f "[d]ocker build -f Dockerfile -t h2-checker-venvs:b43e88d1" >/dev/null || pgrep -f "[d]ocker tag h2-checker" >/dev/null; do sleep 30; done; sleep 5
grep -q BUILD_OK $R/build.log || { log "image build failed"; echo GATEDONE >> $R/driver.log; exit 3; }
cd ~/wt191fix; W=$PWD
[ "$(git rev-parse HEAD)" = b43e88d1c33d81513eb32f0aa9cbd42ba74057d6 ] || { log "wrong head"; exit 4; }
IMGID=$(sudo docker image inspect -f '{{.Id}}' h2-checker-venvs:b43e88d1)
STAGE=$R/checker-venvs
cid=$(sudo docker create h2-checker-venvs:b43e88d1 /bin/true); sudo docker cp "$cid":/opt/h2-checker-venvs "$STAGE"; sudo docker rm "$cid" >/dev/null
log "stage extracted from h2-checker-venvs:b43e88d1 ($IMGID) size=$(du -sh $STAGE | cut -f1)"
AGENT_IMAGE=h1-env:1022; AGENT_DIGEST=$(sudo docker image inspect -f '{{.Id}}' $AGENT_IMAGE)
# venv preflight: same attach + fail-closed verify the runner does, inside the agent base image
sudo docker run --rm --network none -v $W:/ob:ro -v $STAGE:/h2/checker-venvs:ro -e PYTHONPATH=/ob --entrypoint python3 $AGENT_IMAGE -c '
import os,sys,subprocess,pathlib
from obench.checker_venv import attach_checker_venvs
from obench.checker_env import verify_split_checker_venv, REQUIREMENTS_DIR
d=attach_checker_venvs("/h2/checker-venvs","/tmp/cv-pre")
bad=0
for req in sorted(pathlib.Path(REQUIREMENTS_DIR).glob("*.txt")):
    t=req.stem
    try:
        py=verify_split_checker_venv(d,"/ob/data/packs/openbench-tb-hard/"+t)
        v=subprocess.run([str(py),"-c","import sys,pytest;print(sys.version.split()[0])"],capture_output=True,text=True)
        print("PREFLIGHT",t,"OK",py,"->",os.path.realpath(py),v.stdout.strip())
    except Exception as e:
        bad+=1; print("PREFLIGHT",t,"FAIL",type(e).__name__,e)
sys.exit(1 if bad else 0)' > $R/preflight.log 2>&1
prc=$?; log "venv preflight rc=$prc"
[ $prc -eq 0 ] || { log "preflight failed; not launching"; echo GATEDONE >> $R/driver.log; exit 5; }
python3 $W/thesis/ab/h2env/spend_monitor.py --self-test > $R/selftest.log 2>&1 || { log "spend self-test failed; not launching"; echo GATEDONE >> $R/driver.log; exit 8; }
log "$(cat $R/selftest.log)"
cp ~/h2/h2prs.csv $R/h2/
cat > $R/h2/run1.sh <<'IN'
#!/bin/bash
set -u
export OBENCH_HARBOR_APP_REWRITE=1
git config --global --add safe.directory '*'
[ -x /venv/bin/python ] || { python3 -m venv /venv && /venv/bin/pip install -q -e /ob; }
mkdir -p /h2/out
cd /ob && exec /venv/bin/python -m thesis.ab.run_ab /h2/h2prs.csv --pr 4204 --trials 1 \
  --tasks-dir /ob/data/packs/openbench-tb-hard --tasks torch-tensor-parallelism --timeout 2400 --timeout-cap-s 2400 --cell-meta \
  --jobs 2 --vertex-model claude-opus-5-5 --out /h2/out/opus/4204 --cache /h1/opencode-src --order interleave-seeded --seed 1022 \
  --max-cost-usd 5 > /h2/out/run.log 2>&1
IN
chmod +x $R/h2/run1.sh
sudo docker run --rm --network none --entrypoint python3 $AGENT_IMAGE -c 'import torch' >/tmp/h1-torch.out 2>/tmp/h1-torch.err; h1rc=$?
PROBE=$(PYTHONPATH=$W python3 -c 'from obench.checker_venv import normalize_torch_probe; import pathlib; print(normalize_torch_probe('"$h1rc"', pathlib.Path("/tmp/h1-torch.err").read_text()))')
log "start gate191b runner=$(git rev-parse HEAD) agent=$AGENT_IMAGE($AGENT_DIGEST) checker_venvs=h2-checker-venvs:b43e88d1($IMGID) binary_source=original free=$(df -BG --output=avail / | tail -1)"
sudo docker run -d --name gate191b --network host -e OBENCH_ADC_METADATA=1 -e GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d -e VERTEX_LOCATION=global -e OBENCH_VM_TYPE=n2-standard-16 -e OBENCH_AGENT_IMAGE=$AGENT_IMAGE -e OBENCH_AGENT_IMAGE_DIGEST=$AGENT_DIGEST -e OBENCH_CHECKER_VENV_STAGE=/h2/checker-venvs -e OBENCH_H1_TORCH_PROBE="$PROBE" -e TZ=America/New_York -v $W:/ob -v $HOME/h1:/h1 -v $R/h2:/h2 -v $STAGE:/h2/checker-venvs:ro $AGENT_IMAGE /h2/run1.sh >> $R/driver.log
while sudo docker ps -q -f name=gate191b | grep -q .; do
  C=$(python3 $W/thesis/ab/h2env/spend_monitor.py "$R/h2" | sed -n 's/^spend=\([0-9.]*\).*/\1/p'); C=${C:-0}
  log "spend=\$$C free=$(df -BG --output=avail / | tail -1 | tr -dc 0-9)G cells=$(find $R/h2 -path '*/cells/*' -name '*.json' | wc -l)"
  if python3 -c "import sys;sys.exit(0 if $C>=5 else 1)"; then echo "STOP spend $C" > $R/STOPPED; sudo docker stop -t 30 gate191b; fi
  sleep 60; done
log "end exit=$(sudo docker inspect -f '{{.State.ExitCode}}' gate191b) final_spend=$(python3 $W/thesis/ab/h2env/spend_monitor.py $R/h2)"
echo GATEDONE >> $R/driver.log
