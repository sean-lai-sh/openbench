#!/bin/bash
# H2 env-rerun driver (VM host). Produced env-rerun-1031c (3052) and the 13090/13331 --cells reruns.
# usage: [PFX=name] [STOPAT=usd] env_rerun_drive.sh SPECFILE OUTDIR(relative to ~/h2)
# SPEC line: <model> <pr> <pin> <rerun-from (container path)> [cells for --cells]
# Refuses before launch on: spend self-test failure, image ID != DIG, no GCE metadata,
# or any spec line whose pin differs from the rev2 pin table (pin_table_check.py).
# Local guards: this VM's run spend >= STOPAT, disk < 15G, or any pair >= $1.00 (stops that container).
# The binding combined $297-cumulative stop runs centrally (env_rerun_central.sh).
set -u
PFX=${PFX:-e1031}; STOPAT=${STOPAT:?set STOPAT = this VM share of the remaining headroom}
OB=${OB:-$HOME/wt-env1031b}; R=$HOME/h2/$2; GR=/h2/$2; SPEC=$1; mkdir -p $R
H=$OB/thesis/ab/h2env
IMAGE=h2-env:1022; DIG=sha256:72c59033194aae26f6de67c62c77d742aef1d71849000e308f3ee875ff5169ff
COMMIT=$(git -C $OB rev-parse HEAD)
MD=http://metadata.google.internal/computeMetadata/v1/instance
VMN=$(curl -s -H Metadata-Flavor:Google $MD/name); IID=$(curl -s -H Metadata-Flavor:Google $MD/id)
log(){ echo "$(TZ=America/New_York date '+%F %T %Z') $*" >> $R/driver.log; }
python3 $H/spend_monitor.py --self-test >> $R/guard.log 2>&1 || { log "REFUSE self-test"; exit 8; }
[ "$(sudo docker image inspect -f '{{.Id}}' $IMAGE)" = "$DIG" ] || { log "REFUSE image"; exit 8; }
[ -n "$VMN" ] && [ -n "$IID" ] || { log "REFUSE metadata"; exit 8; }
while read -r m pr pin src cells; do
 [ -z "$m" ] && continue
 msg=$(python3 $H/pin_table_check.py --pr $pr --model $m --pin $pin) || { log "$msg"; exit 9; }; log "$msg"
done < $SPEC
cp $SPEC $R/spec.txt
cat > $R/cell.sh <<'IN'
#!/bin/bash
set -u
M=$1 PR=$2 PIN=$3 OUT=$4 SRC=$5 CELLS=${6:-}
export OBENCH_HARBOR_APP_REWRITE=1 OBENCH_PROVIDER_PIN_ROOT=/h1/opencode-src/provider-pins OBENCH_ANTHROPIC_PIN=$PIN
T=dna-insert,filter-js-from-html,model-extraction-relu-logits,polyglot-rust-c,regex-chess,sam-cell-seg,torch-pipeline-parallelism,torch-tensor-parallelism,video-processing
git config --global --add safe.directory '*'
[ -x /venv/bin/python ] || { python3 -m venv /venv && /venv/bin/pip install -q -e /ob; }
mkdir -p $OUT; cd /ob
X=(); [ -n "$CELLS" ] && X=(--cells "$CELLS")
exec /venv/bin/python -m thesis.ab.run_ab /h2/h2prs.csv --pr $PR --trials 10 --tasks-dir /ob/data/packs/openbench-tb-hard --tasks $T \
 --timeout 2400 --timeout-cap-s 2400 --cell-meta --jobs 4 --vertex-model $M --out $OUT --rerun-from $SRC --cache /h1/opencode-src \
 --order interleave-seeded --seed 1022 --runner-commit $OBENCH_RUNNER_COMMIT "${X[@]}" > $OUT/run.log 2>&1
IN
chmod +x $R/cell.sh
log "start vm=$VMN instance_id=$IID code=$COMMIT image=$IMAGE@$DIG stop_at=\$$STOPAT pair_cap=\$1.00 spec=$(tr '\n' ';' < $SPEC)"
NAMES=()
while read -r m pr pin src cells; do
 [ -z "$m" ] && continue; n=$PFX-$m
 sudo docker run -d --name $n --network host -e OBENCH_ADC_METADATA=1 -e GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d -e VERTEX_LOCATION=global \
  -e OBENCH_VM_TYPE=n2-standard-16 -e OBENCH_VM_NAME=$VMN -e OBENCH_INSTANCE_ID=$IID -e TZ=America/New_York -e OBENCH_RUNNER_COMMIT=$COMMIT \
  -e OBENCH_CELL_IMAGE=$IMAGE@$DIG -v $OB:/ob -v $HOME/h1:/h1 -v $HOME/h2:/h2 $IMAGE $GR/cell.sh claude-$m-5-5 $pr $pin $GR/$m $src "$cells" >> $R/driver.log
 NAMES+=($n)
done < $SPEC
while sudo docker ps -q -f name=$PFX- | grep -q .; do
 P=$(sudo python3 $H/pair_spend.py $R); C=$(echo "$P" | sed -n 's/^total=\([0-9.]*\).*/\1/p'); C=${C:-0}
 F=$(df -BG --output=avail / | tail -1 | tr -dc 0-9)
 echo "$(TZ=America/New_York date '+%F %T %Z') spend=\$$C $(echo "$P" | head -1 | cut -d' ' -f2-) free=${F}G" >> $R/spend.log
 echo "$P" | grep '^OVER' | while read -r _ m k v; do grep -qF "$k" $R/paircap.log 2>/dev/null || { log "PAIRCAP $k \$$v stop $PFX-$m"; echo "$k $v" >> $R/paircap.log; sudo docker stop -t 30 $PFX-$m; }; done
 if python3 -c "import sys;sys.exit(0 if $C>=$STOPAT else 1)"; then echo "STOP spend $C" > $R/STOPPED; sudo docker stop -t 30 "${NAMES[@]}"; fi
 [ ${F:-0} -lt 15 ] && { echo "STOP disk ${F}G" > $R/STOPPED; sudo docker stop -t 30 "${NAMES[@]}"; }
 sleep 60
done
for n in "${NAMES[@]}"; do sudo docker logs $n > $R/container-${n#$PFX-}.log 2>&1; log "end $n exit=$(sudo docker inspect -f '{{.State.ExitCode}}' $n)"; done
log "driver done $(cat $R/STOPPED 2>/dev/null)"
