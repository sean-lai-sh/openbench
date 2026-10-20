import json,glob,sys,csv
sys.path.insert(0,'/tmp/ob-s6run'); from thesis.ab.summarize import row_cost
sha={'omp-'+r['#']:(r['Parent/base SHA'],r['Merge commit SHA']) for r in csv.DictReader(open('/workspace/openbench-ab/results/step7-opus-1019/pi-harness-prs-step7.csv'))}
T=0
for f in sorted(glob.glob(sys.argv[1]+'/omp-*/cells/*/*/*.json')):
  r=json.load(open(f)); p=f.split('/'); row=p[-5]; side=p[-3]; c=row_cost(r) or 0; T+=c
  b=r['cmd'][0].split('/')[-2]; want=sha[row][1 if side=='with' else 0]
  print(row,side,p[-1][:-5],r.get('failure_class'),r.get('upstream_model'),r.get('params_stripped_requests'),round(c,3),'own-sha' if b==want else 'SHA-MISMATCH '+b[:10],str(r.get('error') or '')[:90].replace('\n',' '))
print('cost',round(T,2))
