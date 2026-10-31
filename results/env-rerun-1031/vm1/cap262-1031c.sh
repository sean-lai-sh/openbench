#!/bin/bash
# VM1 local cap override: the running 1031c driver has STOPAT=285; this lowers it to $262 (its share of the ~$279.5 headroom).
R=$HOME/h2/env-rerun-1031c
while sudo docker ps -q -f name=e1031c- | grep -q .; do
 C=$(sudo python3 ~/h2/pairs1031.py $R | sed -n "s/^total=\([0-9.]*\).*/\1/p")
 if python3 -c "import sys;sys.exit(0 if ${C:-0}>=262 else 1)"; then echo "STOP local cap262 spend $C" > $R/STOPPED; sudo docker stop -t 30 e1031c-sonnet e1031c-opus; fi
 sleep 60; done
