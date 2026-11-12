#!/bin/bash
# Re-smoke for the D1 Sonnet prompt follow-up, runner 04521ae5 (#248 on main).
# One cell per arm, --model and --vertex-model both claude-sonnet-5-5, cap $3.
# Do not launch the 30/side job from this script.
set -u
OB=$HOME/ob-s248
R=$HOME/h2/d1fu-resmoke248-1112
IMAGE=h2-env:1022
DIG=sha256:72c59033194aae26f6de67c62c77d742aef1d71849000e308f3ee875ff5169ff
WANT=04521ae557a04fc3de5256dd1ed40b46ff1c4817
mkdir -p "$R"
log(){ echo "$(TZ=America/New_York date '+%F %T %Z') $*" | tee -a "$R/driver.log"; }
COMMIT=$(git -C "$OB" rev-parse HEAD)
if [ "$COMMIT" != "$WANT" ]; then
  log "REFUSE head $COMMIT != $WANT"
  exit 8
fi
ID=$(sudo docker image inspect -f '{{.Id}}' $IMAGE)
if [ "$ID" != "$DIG" ]; then
  log "REFUSE image digest mismatch got=$ID want=$DIG"
  exit 8
fi
F=$(df -BG --output=avail / | tail -1 | tr -dc 0-9)
if [ "$F" -lt 15 ]; then
  log "REFUSE free ${F}G<15G"
  exit 8
fi
if sudo docker inspect d1fu-resmoke248 >/dev/null 2>&1; then
  log "REFUSE container d1fu-resmoke248 already exists"
  exit 8
fi
cp -a $HOME/h2/d1-prompt-fu-1112b/prs.csv $HOME/h2/d1-prompt-fu-1112b/task-map.csv "$R/"
cp -a $HOME/h2/d1fu-resmoke248-1112-scripts/cell.sh "$R/cell.sh"
cp -a $HOME/h2/d1fu-resmoke248-1112-scripts/config-check.py "$R/config-check.py"
cp -a $HOME/h2/d1fu-resmoke248-1112-scripts/gate-check.py "$R/gate-check.py"
chmod +x "$R/cell.sh"
log "start d1fu-resmoke248 vm=$(hostname -s) code=$COMMIT image=$IMAGE@$DIG max-cost-usd=3 trials=1/side seed=1016 flags=--model claude-sonnet-5-5 --vertex-model claude-sonnet-5-5 free=${F}G"
sudo docker run -d --name d1fu-resmoke248 --network host \
  -e OBENCH_ADC_METADATA=1 -e GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d -e VERTEX_LOCATION=global \
  -e OBENCH_VM_TYPE=n2-standard-16 -e OBENCH_VM_NAME=<HOST> -e TZ=America/New_York \
  -e OBENCH_RUNNER_COMMIT=$COMMIT \
  -e PATH=/h1/opencode-src/go/1.24.6/bin:/h1/toolchain/node-v20.19.2-linux-x64/bin:/root/.local/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
  -v "$OB":/ob -v $HOME/h1:/h1 -v "$R":/o \
  $IMAGE@$DIG bash -c 'git config --global --add safe.directory "*"; exec /o/cell.sh'
log "docker started name=d1fu-resmoke248 id=$(sudo docker inspect -f '{{.Id}}' d1fu-resmoke248)"
