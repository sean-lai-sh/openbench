#!/bin/bash
# D1 Sonnet prompt follow-up, 30/side, runner 04521ae5, cap $25, with per-call body capture.
set -u
OB=$HOME/ob-s248
R=$HOME/h2/d1fu-30-1112
S=$HOME/h2/d1fu-30-1112-scripts
NAME=d1fu-30
IMAGE=h2-env:1022
DIG=sha256:72c59033194aae26f6de67c62c77d742aef1d71849000e308f3ee875ff5169ff
WANT=04521ae557a04fc3de5256dd1ed40b46ff1c4817
mkdir -p "$R"
log(){ echo "$(TZ=America/New_York date '+%F %T %Z') $*" | tee -a "$R/driver.log"; }
COMMIT=$(git -C "$OB" rev-parse HEAD)
[ "$COMMIT" = "$WANT" ] || { log "REFUSE head $COMMIT != $WANT"; exit 8; }
[ -z "$(git -C "$OB" status --porcelain --untracked-files=no)" ] || { log "REFUSE dirty tree"; exit 8; }
ID=$(sudo docker image inspect -f '{{.Id}}' $IMAGE)
[ "$ID" = "$DIG" ] || { log "REFUSE image digest mismatch got=$ID want=$DIG"; exit 8; }
F=$(df -BG --output=avail / | tail -1 | tr -dc 0-9)
[ "$F" -ge 15 ] || { log "REFUSE free ${F}G<15G"; exit 8; }
if sudo docker inspect $NAME >/dev/null 2>&1; then log "REFUSE container $NAME already exists"; exit 8; fi
[ -z "$(sudo docker ps -q)" ] || { log "REFUSE other containers running"; exit 8; }
cp -a $HOME/h2/d1-prompt-fu-1112b/prs.csv $HOME/h2/d1-prompt-fu-1112b/task-map.csv "$R/"
cp -a $S/cell.sh $S/capture_run_ab.py $S/launch-d1fu30.sh "$R/"
cp -a $HOME/h2/d1fu-resmoke248-1112-scripts/config-check.py $HOME/h2/d1fu-resmoke248-1112-scripts/gate-check.py "$R/"
chmod +x "$R/cell.sh"
log "start $NAME vm=$(hostname -s) code=$COMMIT image=$IMAGE@$DIG max-cost-usd=25 trials=30/side seed=1016 flags=--model claude-sonnet-5-5 --vertex-model claude-sonnet-5-5 bodies=/o/request-bodies free=${F}G"
sudo docker run -d --name $NAME --network host \
  -e OBENCH_ADC_METADATA=1 -e GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d -e VERTEX_LOCATION=global \
  -e OBENCH_VM_TYPE=n2-standard-16 -e OBENCH_VM_NAME=<HOST> -e TZ=America/New_York \
  -e OBENCH_RUNNER_COMMIT=$COMMIT \
  -e PATH=/h1/opencode-src/go/1.24.6/bin:/h1/toolchain/node-v20.19.2-linux-x64/bin:/root/.local/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
  -v "$OB":/ob -v $HOME/h1:/h1 -v "$R":/o \
  $IMAGE@$DIG bash -c 'git config --global --add safe.directory "*"; exec /o/cell.sh'
log "docker started name=$NAME id=$(sudo docker inspect -f '{{.Id}}' $NAME)"
# keep tmux pane alive while the container runs
sudo docker wait $NAME | sed "s/^/container exit=/" | tee -a "$R/driver.log"
log "container finished"
