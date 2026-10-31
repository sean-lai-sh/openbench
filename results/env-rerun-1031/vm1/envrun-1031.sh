#!/bin/bash
# env rerun 1031 driver (VM host). 3052 full pairs, pin @ai-sdk/anthropic 2.0.25, runner 2f66aacf, image h2-env:1022.
# Stop: run spend >= $285 (prior env spend ~$12.1, so cumulative stays under the $300 env stop), or disk < 15 GB.
set -u
OB=$HOME/wt-env1031; R=$HOME/h2/env-rerun-1031; GR=/h2/env-rerun-1031; mkdir -p $R
IMAGE=h2-env:1022; DIG=sha256:72c59033194aae26f6de67c62c77d742aef1d71849000e308f3ee875ff5169ff
COMMIT=$(git -C $OB rev-parse HEAD); STOPAT=${STOPAT:-285}
log(){ echo "$(TZ=America/New_York date '+%F %T %Z') $*" >> $R/driver.log; }
python3 $OB/thesis/ab/h2env/spend_monitor.py --self-test >> $R/guard.log 2>&1 || { log "REFUSE self-test"; exit 8; }
[ "$(sudo docker image inspect -f '{{.Id}}' $IMAGE)" = "$DIG" ] || { log "REFUSE image"; exit 8; }
cat > $R/cell.sh <<'IN'
#!/bin/bash
set -u
M=$1 OUT=$2 SRC=$3
export OBENCH_HARBOR_APP_REWRITE=1 OBENCH_PROVIDER_PIN_ROOT=/h1/opencode-src/provider-pins OBENCH_ANTHROPIC_PIN=2.0.25
T=dna-insert,filter-js-from-html,model-extraction-relu-logits,polyglot-rust-c,regex-chess,sam-cell-seg,torch-pipeline-parallelism,torch-tensor-parallelism,video-processing
git config --global --add safe.directory '*'
[ -x /venv/bin/python ] || { python3 -m venv /venv && /venv/bin/pip install -q -e /ob; }
mkdir -p $OUT; cd /ob
exec /venv/bin/python -m thesis.ab.run_ab /h2/h2prs.csv --pr 3052 --trials 10 --tasks-dir /ob/data/packs/openbench-tb-hard --tasks $T \
 --timeout 2400 --timeout-cap-s 2400 --cell-meta --jobs 4 --vertex-model $M --out $OUT --rerun-from $SRC --cache /h1/opencode-src \
 --order interleave-seeded --seed 1022 --runner-commit $OBENCH_RUNNER_COMMIT > $OUT/run.log 2>&1
IN
chmod +x $R/cell.sh
log "start env rerun 3052 pin=2.0.25 code=$COMMIT image=$IMAGE@$DIG stop_at=\$$STOPAT"
for m in sonnet opus; do
 sudo docker run -d --name env-$m --network host -e OBENCH_ADC_METADATA=1 -e GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d -e VERTEX_LOCATION=global \
  -e OBENCH_VM_TYPE=n2-standard-16 -e TZ=America/New_York -e OBENCH_RUNNER_COMMIT=$COMMIT -e OBENCH_CELL_IMAGE=$IMAGE@$DIG \
  -v $OB:/ob -v $HOME/h1:/h1 -v $HOME/h2:/h2 $IMAGE $GR/cell.sh claude-$m-5-5 $GR/$m /h2/h2-hardsuite-1022/$m >> $R/driver.log
done
while sudo docker ps -q -f name=env- | grep -q .; do
 C=$(sudo python3 $OB/thesis/ab/h2env/spend_monitor.py "$R" | sed -n 's/^spend=\([0-9.]*\).*/\1/p'); C=${C:-0}
 F=$(df -BG --output=avail / | tail -1 | tr -dc 0-9)
 echo "$(TZ=America/New_York date '+%F %T %Z') spend=\$$C free=${F}G cells=$(sudo find $R -path '*/cells/*' -name '*.json' | wc -l)" >> $R/spend.log
 if python3 -c "import sys;sys.exit(0 if $C>=$STOPAT else 1)"; then echo "STOP spend $C" > $R/STOPPED; sudo docker stop -t 30 env-sonnet env-opus; fi
 [ $F -lt 15 ] && { echo "STOP disk ${F}G" > $R/STOPPED; sudo docker stop -t 30 env-sonnet env-opus; }
 sleep 60
done
for m in sonnet opus; do sudo docker logs env-$m > $R/container-$m.log 2>&1; log "end $m exit=$(sudo docker inspect -f '{{.State.ExitCode}}' env-$m)"; sudo docker rm env-$m >/dev/null; done
log "driver done $(cat $R/STOPPED 2>/dev/null)"
