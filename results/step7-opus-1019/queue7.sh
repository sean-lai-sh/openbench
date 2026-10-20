#!/bin/bash
# Step-7 queue: one invocation at a time (run.sh itself waits while any run_ab is alive). Stops if a QUEUE-STOP appears.
R=/workspace/openbench-ab/results; S=$R/step7-opus-1019
while pgrep -f "thesis.ab.run_ab" >/dev/null; do sleep 30; done
[ -e $S/QUEUE-STOP ] && exit 1; [ -e $S/HOLD-7 ] && exit 0
BATCHCAP=162 bash $S/run.sh $R/step7-opus-1019-S7B S7B 30 default omp-24,omp-26,omp-28,omp-39,omp-43
[ -e $S/QUEUE-STOP ] && exit 1; [ -e $S/HOLD-7 ] && exit 0
BATCHCAP=179 bash $S/run.sh $R/step7-opus-1019-S7C S7C 30 off omp-30,omp-31,omp-32
