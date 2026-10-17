# Step-4 resume after the invalid smoke (#76): re-smoke all 15 rows (venv on PATH, runner #81), gate, then B1, B2, B3(off). One invocation at a time.
R=/workspace/openbench-ab/results; S=$R/step4-omp-sonnet-1017; PY=/workspace/openbench-ab/.venv/bin/python
D="omp-15,omp-16,omp-21,omp-28,omp-33,omp-35,omp-36,omp-38,omp-39,omp-43,omp-44"; OFF="omp-19,omp-30,omp-31,omp-32"
stop() { [ -e $S/QUEUE-STOP ] && { echo "$(date '+%F %T %Z') queue4 halted: $(cat $S/QUEUE-STOP)" >> $S/driver.log; exit 1; }; }
bash $S/run.sh $R/step4-omp-sonnet-1017-smoke2 smoke2-default 1 default $D; stop
bash $S/run.sh $R/step4-omp-sonnet-1017-smoke2-off smoke2-off 1 off $OFF; stop
$PY - <<'PY' || { echo "$(date '+%F %T %Z') smoke2 FAILED gate" | tee -a $S/QUEUE-STOP >> $S/driver.log; exit 1; }
import json,glob,sys
bad=[];n=0
for p in glob.glob('/workspace/openbench-ab/results/step4-omp-sonnet-1017-smoke2*/*/cells/*/*/*.json'):
    r=json.load(open(p)); n+=1
    if r.get('failure_class') in ('infra','incompatible','rate_limited','stalled') or r.get('upstream_model')!='claude-sonnet-5-5' or not r.get('requests_output') or 'No module named pytest' in json.dumps(r): bad.append((p.split('/')[-5],p.split('/')[-3],r.get('failure_class')))
inc=glob.glob('/workspace/openbench-ab/results/step4-omp-sonnet-1017-smoke2*/*/*.incompatible.json')
print(n,bad,inc); sys.exit(0 if n==30 and not bad and not inc else 1)
PY
echo "$(date '+%F %T %Z') smoke2 gate ok (30 cells, sonnet, metered, no pytest error)" >> $S/driver.log
bash $S/run.sh $R/step4-omp-sonnet-1017 B1 30 default omp-15,omp-16,omp-21,omp-28,omp-33,omp-35; stop; echo "$(date '+%F %T %Z') B1 done" >> $S/driver.log
bash $S/run.sh $R/step4-omp-sonnet-1017 B2 30 default omp-36,omp-38,omp-39,omp-43,omp-44; stop; echo "$(date '+%F %T %Z') B2 done" >> $S/driver.log
bash $S/run.sh $R/step4-omp-sonnet-1017-off B3 30 off $OFF; stop; echo "$(date '+%F %T %Z') B3 done" >> $S/driver.log
