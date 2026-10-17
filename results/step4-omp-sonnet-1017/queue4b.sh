# queue4b: after smoke2 (#88, 29/30 clean): re-smoke omp-19 (ADC refresh timeout), gate, then B1, B2, B3(off). One invocation at a time.
R=/workspace/openbench-ab/results; S=$R/step4-omp-sonnet-1017; PY=/workspace/openbench-ab/.venv/bin/python
D="omp-15,omp-16,omp-21,omp-28,omp-33,omp-35,omp-36,omp-38,omp-39,omp-43,omp-44"; OFF="omp-19,omp-30,omp-31,omp-32"
stop() { [ -e $S/QUEUE-STOP ] && { echo "$(date '+%F %T %Z') queue4 halted: $(cat $S/QUEUE-STOP)" >> $S/driver.log; exit 1; }; }
bash $S/run.sh $R/step4-omp-sonnet-1017-smoke3-19 smoke3-19 1 off omp-19; stop
$PY - <<'PY' || { echo "$(date '+%F %T %Z') smoke3-19 FAILED gate" | tee -a $S/QUEUE-STOP >> $S/driver.log; exit 1; }
import json,glob,sys
rs=[json.load(open(p)) for p in glob.glob('/workspace/openbench-ab/results/step4-omp-sonnet-1017-smoke3-19/omp-19/cells/*/*/*.json')]
ok=[r for r in rs if r.get('failure_class') not in ('infra','incompatible','rate_limited','stalled') and r.get('upstream_model')=='claude-sonnet-5-5' and r.get('requests_output') and 'No module named pytest' not in json.dumps(r)]
print(len(rs),len(ok)); sys.exit(0 if len(rs)==2 and len(ok)==2 else 1)
PY
echo "$(date '+%F %T %Z') smoke3-19 gate ok" >> $S/driver.log
bash $S/run.sh $R/step4-omp-sonnet-1017 B1 30 default omp-15,omp-16,omp-21,omp-28,omp-33,omp-35; stop; echo "$(date '+%F %T %Z') B1 done" >> $S/driver.log
bash $S/run.sh $R/step4-omp-sonnet-1017 B2 30 default omp-36,omp-38,omp-39,omp-43,omp-44; stop; echo "$(date '+%F %T %Z') B2 done" >> $S/driver.log
bash $S/run.sh $R/step4-omp-sonnet-1017-off B3 30 off $OFF; stop; echo "$(date '+%F %T %Z') B3 done" >> $S/driver.log
