#!/bin/bash
# Step-7 queue b (replaces queue7's S7-C step via HOLD-7): S7-C thinking off = 30,31,32 + 26 (PM 23:13 ET), then row-24 rerun. One invocation at a time.
R=/workspace/openbench-ab/results; S=$R/step7-opus-1019
while pgrep -f "queue7.sh" >/dev/null || pgrep -f "thesis.ab.run_ab" >/dev/null; do sleep 30; done
[ -e $S/QUEUE-STOP ] && exit 1
BATCHCAP=236 bash $S/run.sh $R/step7-opus-1019-S7C S7C 30 off omp-30,omp-31,omp-32,omp-26
[ -e $S/QUEUE-STOP ] && exit 1
BATCHCAP=31 bash $S/run.sh $R/step7-opus-1019-R24 R24 30 default omp-24
