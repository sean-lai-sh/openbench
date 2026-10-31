#!/bin/bash
# VM1 local cap $270 across env-rerun-1031c (3052 sonnet) + env-rerun-1031d (3052 opus --cells); replaces cap262/cap270-1031c.
while sudo docker ps -q -f name=e1031 | grep -q .; do
 C=$(sudo python3 ~/wt-main1031/thesis/ab/h2env/pair_spend.py ~/h2/env-rerun-1031c ~/h2/env-rerun-1031d | sed -n "s/^total=\([0-9.]*\).*/\1/p")
 if python3 -c "import sys;sys.exit(0 if ${C:-0}>=270 else 1)"; then echo "STOP vm1 local cap270 spend $C" | tee ~/h2/env-rerun-1031c/STOPPED > ~/h2/env-rerun-1031d/STOPPED; sudo docker stop -t 30 e1031c-sonnet e1031f-opus; fi
 sleep 60; done
