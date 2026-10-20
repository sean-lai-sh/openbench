import json,glob,sys; sys.path.insert(0,'/tmp/ob-s6run'); from thesis.ab.summarize import row_cost
T=0
for p in sorted(glob.glob(sys.argv[1]+'/*/cells/*/*/*.json')):
  r=json.load(open(p)); c=row_cost(r) or 0; T+=c
  if len(sys.argv)<3: print(p.split('/')[-5],p.split('/')[-3],p.split('/')[-1][:-5],r.get('failure_class'),r.get('upstream_model'),round(c,3),str(r.get('error') or '')[:90].replace('\n',' '))
print('total',round(T,2))
