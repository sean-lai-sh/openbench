#!/bin/bash
# PR #243 gate smoke: one cell per arm, Sonnet via proxy, runner 151e349c. Cap $3 per form.
set -u
OB=$HOME/ob-s243
R=$HOME/h2/d1fu-smoke243-1112
IMAGE=h2-env:1022
DIG=sha256:72c59033194aae26f6de67c62c77d742aef1d71849000e308f3ee875ff5169ff
mkdir -p "$R/A-model-vertex" "$R/B-model-only"
log(){ echo "$(TZ=America/New_York date '+%F %T %Z') $*" >> "$R/driver.log"; }
[ -d "$OB" ] || git -C $HOME/ob worktree add --detach "$OB" 151e349cbe6edd40855273115502f5ac2d7f54a9 >> "$R/driver.log" 2>&1
COMMIT=$(git -C "$OB" rev-parse HEAD)
[ "$COMMIT" = 151e349cbe6edd40855273115502f5ac2d7f54a9 ] || { log "REFUSE head $COMMIT"; exit 8; }
[ "$(sudo docker image inspect -f '{{.Id}}' $IMAGE)" = "$DIG" ] || { log "REFUSE image digest mismatch"; exit 8; }
F=$(df -BG --output=avail / | tail -1 | tr -dc 0-9)
[ "$F" -lt 15 ] && { log "REFUSE free ${F}G<15G"; exit 8; }
for d in A-model-vertex B-model-only; do cp -a $HOME/h2/d1-prompt-fu-1112b/prs.csv $HOME/h2/d1-prompt-fu-1112b/task-map.csv "$R/$d/"; done
log "start d1fu-smoke243 vm=$(hostname -s) code=$COMMIT image=$IMAGE@$DIG max-cost-usd=3/form trials=1/side seed=1016 free=${F}G"
cat > "$R/cell.sh" <<'IN'
#!/bin/bash
set -u
export OBENCH_HARBOR_APP_REWRITE=1
git config --global --add safe.directory '*'
[ -x /venv/bin/python ] || { python3 -m venv /venv && /venv/bin/pip install -q -e /ob; }
cd /ob
common=(--task-map /o/A-model-vertex/task-map.csv --tasks-dir /ob/tasks --trials 1 --jobs 2
  --order interleave-seeded --seed 1016 --max-cost-usd 3 --cell-meta --cache /h1/opencode-src
  --timeout 2400 --timeout-cap-s 2400 --runner-commit "$OBENCH_RUNNER_COMMIT")
/venv/bin/python -m thesis.ab.run_ab /o/A-model-vertex/prs.csv --pr 725226 --model claude-sonnet-5-5 --vertex-model claude-sonnet-5-5 --dry-run "${common[@]}" --out /o/A-model-vertex > /o/A-model-vertex/dry-run.txt 2>&1; echo "exit=$?" >> /o/A-model-vertex/dry-run.txt
/venv/bin/python -m thesis.ab.run_ab /o/B-model-only/prs.csv --pr 725226 --model claude-sonnet-5-5 --dry-run "${common[@]}" --out /o/B-model-only > /o/B-model-only/dry-run.txt 2>&1; echo "exit=$?" >> /o/B-model-only/dry-run.txt
/venv/bin/python -m thesis.ab.run_ab /o/A-model-vertex/prs.csv --pr 725226 --model claude-sonnet-5-5 --vertex-model claude-sonnet-5-5 "${common[@]}" --out /o/A-model-vertex > /o/A-model-vertex/run.log 2>&1
a=$?; echo "exit=$a" >> /o/A-model-vertex/run.log
[ $a -eq 0 ] && { /venv/bin/python -m thesis.ab.run_ab /o/B-model-only/prs.csv --pr 725226 --model claude-sonnet-5-5 "${common[@]}" --out /o/B-model-only > /o/B-model-only/run.log 2>&1; echo "exit=$?" >> /o/B-model-only/run.log; }
touch /o/DONE
IN
chmod +x "$R/cell.sh"
sudo docker run -d --name d1fu-smoke243 --network host \
  -e OBENCH_ADC_METADATA=1 -e GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d -e VERTEX_LOCATION=global \
  -e OBENCH_VM_TYPE=n2-standard-16 -e OBENCH_VM_NAME=thesis-h1-cpu-3 -e TZ=America/New_York \
  -e OBENCH_RUNNER_COMMIT=$COMMIT \
  -e PATH=/h1/opencode-src/go/1.24.6/bin:/h1/toolchain/node-v20.19.2-linux-x64/bin:/root/.local/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
  -v "$OB":/ob -v $HOME/h1:/h1 -v "$R":/o \
  $IMAGE@$DIG bash -c 'git config --global --add safe.directory "*"; exec /o/cell.sh'
log "docker started name=d1fu-smoke243"
