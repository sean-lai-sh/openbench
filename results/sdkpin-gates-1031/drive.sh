#!/bin/bash
# sdkpin gate driver (VM host), 2026-10-31. Pairs sequential. Stops: $1.00/pair, $8 total,
# spend_monitor self-test or image digest failure (same guard as #213 h2.sh).
set -u
G=$HOME/h2/sdkpin-gates-1031; OB=$HOME/wt-g1031; mkdir -p $G
H2_IMAGE_DIGEST=sha256:72c59033194aae26f6de67c62c77d742aef1d71849000e308f3ee875ff5169ff
log(){ echo "$(TZ=America/New_York date '+%F %T %Z') $*" | tee -a $G/driver.log; }
guard(){
  python3 $OB/thesis/ab/h2env/spend_monitor.py --self-test >>$G/guard.log 2>&1 || { log "REFUSE: spend_monitor --self-test failed"; exit 8; }
  GOT=$(sudo docker image inspect -f '{{.Id}}' h2-env:1022 2>/dev/null)
  [ "$GOT" = "$H2_IMAGE_DIGEST" ] || { log "REFUSE: h2-env:1022 is '$GOT'"; exit 8; }
}
while read PIN PR MODEL BUDGET <&3; do
  [ -z "$PIN" ] && continue
  [ -e $G/STOPPED ] && { log "skip $PIN: $(cat $G/STOPPED)"; continue; }
  guard
  D=$G/$PIN-$PR; [ -e $D/$MODEL ] && { log "skip $PIN: exists"; continue; }
  mkdir -p $D; echo "$BUDGET" > $D/budget.txt
  log "start pair pin=$PIN pr=$PR model=claude-$MODEL-5-5 budget=$BUDGET image=h2-env:1022($H2_IMAGE_DIGEST) code=$(git -C $OB rev-parse HEAD)"
  N=g1031-$(echo $PIN | tr . -)-$PR
  sudo docker run -d --name $N --network host -e OBENCH_ADC_METADATA=1 -e GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d -e VERTEX_LOCATION=global -e OBENCH_VM_TYPE=n2-standard-16 -e TZ=America/New_York -v $OB:/ob -v $HOME/h1:/h1 -v $HOME/h2:/h2 h2-env:1022 /h2/sdkpin-gates-1031/gate1.sh claude-$MODEL-5-5 /h2/sdkpin-gates-1031/$PIN-$PR/$MODEL $PR $PIN >/dev/null
  while sudo docker ps -q -f name=^$N$ | grep -q .; do
    read P T < <(sudo python3 $G/gatewatch.py $D $G $OB)
    echo "$(TZ=America/New_York date '+%F %T %Z') pin=$PIN pair=\$$P total=\$$T" >> $G/spend.log
    if python3 -c "import sys;sys.exit(0 if $T>=8 or $T<0 else 1)"; then echo "STOP total $T" > $G/STOPPED; sudo docker stop -t 30 $N; fi
    if python3 -c "import sys;sys.exit(0 if $P>=1.0 else 1)"; then echo "pair cap $P" > $D/CAPPED; sudo docker stop -t 30 $N; fi
    sleep 10
  done
  sudo docker logs $N > $D/container.log 2>&1; EC=$(sudo docker inspect -f '{{.State.ExitCode}}' $N); sudo docker rm $N >/dev/null
  read P T < <(sudo python3 $G/gatewatch.py $D $G $OB)
  log "end pair pin=$PIN exit=$EC pair=\$$P total=\$$T $(cat $D/CAPPED 2>/dev/null)"
done 3< $G/pairs.txt
log "driver done $(cat $G/STOPPED 2>/dev/null)"
