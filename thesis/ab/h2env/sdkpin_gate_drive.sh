#!/bin/bash
# sdkpin gate driver (VM host). Reads "PIN PR MODEL BUDGET" lines from $G/pairs.txt.
# Stops: $1.00/pair, $8 total, spend_monitor self-test or image digest failure.
# Env: G (gate dir under ~/h2), OB (runner worktree), GATEWATCH (spend watcher).
set -u
G=${G:?set G=~/h2/<gate-dir>}; OB=${OB:?set OB=<runner worktree>}; GATEWATCH=${GATEWATCH:-$G/gatewatch.py}
# PAIR_CAP and TOTAL_CAP are enforced here by stopping the container.
# CELL_CAP (default none) is the in-cell run_ab cap; leave it unset for reruns.
PAIR_CAP=${PAIR_CAP:-1.0}; TOTAL_CAP=${TOTAL_CAP:-8}; CELL_CAP=${CELL_CAP:-}
IMAGE=h2-env:1022
H2_IMAGE_DIGEST=sha256:72c59033194aae26f6de67c62c77d742aef1d71849000e308f3ee875ff5169ff
CELL=/ob/thesis/ab/h2env/sdkpin_gate_cell.sh
GDIR=/h2/${G#$HOME/h2/}
mkdir -p "$G"
log(){ echo "$(TZ=America/New_York date '+%F %T %Z') $*" | tee -a "$G/driver.log"; }
# Resolved on the host, where the worktree's git dir exists, then passed in.
COMMIT=$(git -C "$OB" rev-parse HEAD) || { log "REFUSE: no runner commit"; exit 8; }
[ -n "$COMMIT" ] || { log "REFUSE: empty runner commit"; exit 8; }
guard(){
  python3 "$OB/thesis/ab/h2env/spend_monitor.py" --self-test >>"$G/guard.log" 2>&1 || { log "REFUSE: spend_monitor --self-test failed"; exit 8; }
  GOT=$(sudo docker image inspect -f '{{.Id}}' $IMAGE 2>/dev/null)
  [ "$GOT" = "$H2_IMAGE_DIGEST" ] || { log "REFUSE: $IMAGE is '$GOT'"; exit 8; }
}
while read -r PIN PR MODEL BUDGET <&3; do
  [ -z "${PIN:-}" ] && continue
  [ -e "$G/STOPPED" ] && { log "skip $PIN: $(cat "$G/STOPPED")"; continue; }
  guard
  D=$G/$PIN-$PR; [ -e "$D/$MODEL" ] && { log "skip $PIN: exists"; continue; }
  mkdir -p "$D"; echo "$BUDGET" > "$D/budget.txt"
  log "start pair pin=$PIN pr=$PR model=claude-$MODEL-5-5 budget=$BUDGET image=$IMAGE@$H2_IMAGE_DIGEST code=$COMMIT"
  N=gate-$(echo "$PIN" | tr . -)-$PR
  sudo docker run -d --name "$N" --network host -e OBENCH_ADC_METADATA=1 \
    -e GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:?}" -e VERTEX_LOCATION=global \
    -e OBENCH_VM_TYPE=n2-standard-16 -e TZ=America/New_York \
    -e OBENCH_RUNNER_COMMIT="$COMMIT" -e OBENCH_CELL_IMAGE="$IMAGE@$H2_IMAGE_DIGEST" \
    -v "$OB:/ob" -v "$HOME/h1:/h1" -v "$HOME/h2:/h2" $IMAGE \
    $CELL "claude-$MODEL-5-5" "$GDIR/$PIN-$PR/$MODEL" "$PR" "$PIN" "${TASK:-model-extraction-relu-logits}" "$CELL_CAP" >/dev/null
  while sudo docker ps -q -f name="^$N$" | grep -q .; do
    read -r P T < <(sudo python3 "$GATEWATCH" "$D" "$G" "$OB")
    echo "$(TZ=America/New_York date '+%F %T %Z') pin=$PIN pair=\$$P total=\$$T" >> "$G/spend.log"
    if python3 -c "import sys;sys.exit(0 if $T>=$TOTAL_CAP or $T<0 else 1)"; then echo "STOP total $T" > "$G/STOPPED"; sudo docker stop -t 30 "$N"; fi
    if python3 -c "import sys;sys.exit(0 if $P>=$PAIR_CAP else 1)"; then echo "pair cap $P" > "$D/CAPPED"; sudo docker stop -t 30 "$N"; fi
    sleep 10
  done
  sudo docker logs "$N" > "$D/container.log" 2>&1; EC=$(sudo docker inspect -f '{{.State.ExitCode}}' "$N"); sudo docker rm "$N" >/dev/null
  read -r P T < <(sudo python3 "$GATEWATCH" "$D" "$G" "$OB")
  log "end pair pin=$PIN exit=$EC pair=\$$P total=\$$T $(cat "$D/CAPPED" 2>/dev/null)"
done 3< "$G/pairs.txt"
log "driver done $(cat "$G/STOPPED" 2>/dev/null)"
