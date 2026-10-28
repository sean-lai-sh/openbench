import json,glob,os,math,csv,re,collections
from scipy.stats import fisher_exact
R='repo/results/step8-f032-1027'
comp=json.load(open(f'{R}/complete.json'))
old=json.load(open(f'{R}/complete.20261027-0345.json'))
bcs={l.split()[0]:l.split()[2] for l in open(f'{R}/build_channel_sources.txt') if l.strip()}
def wil(k,n,z=1.96):
  p=k/n;d=1+z*z/n;c=(p+z*z/(2*n))/d;h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d;return c-h,c+h
def newc(k1,n1,k2,n2):
  l1,u1=wil(k1,n1);l2,u2=wil(k2,n2);p1,p2=k1/n1,k2/n2;d=p1-p2
  return d-math.sqrt((p1-l1)**2+(u2-p2)**2), d+math.sqrt((u1-p1)**2+(p2-l2)**2)
issues=[];sides={};allcells=0;tot=0;gtot=0
for side,v in sorted(comp['complete'].items()):
  pr,arm=side.split('/')
  files=sorted(glob.glob(f'{R}/scored/{pr}/cells/{arm}/*/*.json'))
  listed=[p.replace('/home/box/s8f032run/',R+'/') for p in v['cells']]
  if set(listed)!=set(files): issues.append(f'{side}: complete.json list != files ({len(listed)} vs {len(files)})')
  cs=[];routes=set();src=set();models=set()
  for f in files:
    c=json.load(open(f));allcells+=1;tot+=c.get('requests_cost_usd') or 0
    if c.get('strace_on') or c.get('gate_cell'): issues.append(f'{f}: traced/gate in scored');continue
    if (c.get('rerun') or 0)!=0: issues.append(f'{f}: rerun={c["rerun"]}')
    if str(c.get('failure_class','')).startswith('infra') or 'off' in str(c.get('route','')).split(':')[0]: issues.append(f'{f}: infra/off_route {c.get("failure_class")} {c.get("route")}');continue
    mf=[m for m in c.get('missing_fields') or [] if m not in('probe_method','provider_loaded_version')]
    ok=bool(c.get('success')) and not mf
    if mf: issues.append(f'{f}: missing {mf}')
    sha=re.search(r'/bin/([0-9a-f]{40})/',' '.join(c['cmd'])).group(1)
    src.add(bcs.get(sha,'UNRESOLVED:'+sha));routes.add(c.get('route'));models.add((c.get('model'),c.get('upstream_model')))
    cs.append((ok,c.get('requests_cost_usd') or 0,c.get('wall_time_s') or 0,c.get('error'),c.get('failure_class')))
  sides[side]=dict(n=len(cs),k=sum(x[0] for x in cs),cost=sum(x[1] for x in cs)/len(cs),wall=sum(x[2] for x in cs)/len(cs),routes=routes,src=src,models=models,fc=collections.Counter(x[4] for x in cs))
for g in glob.glob(f'{R}/gate/**/*.json',recursive=True):
  try:
    c=json.load(open(g))
    if isinstance(c,dict) and 'requests_cost_usd' in c: gtot+=c['requests_cost_usd'] or 0
  except: pass
prs=sorted({s.split('/')[0] for s in sides});rows=[]
for pr in prs:
  w,o=sides.get(pr+'/with'),sides.get(pr+'/without')
  if not w or not o: rows.append(dict(pr=pr,note='incomplete pair'));continue
  p=fisher_exact([[w['k'],w['n']-w['k']],[o['k'],o['n']-o['k']]])[1]
  rows.append(dict(pr=pr,with_k=w['k'],with_n=w['n'],without_k=o['k'],without_n=o['n'],diff=w['k']/w['n']-o['k']/o['n'],
   with_ci='%.3f-%.3f'%wil(w['k'],w['n']),without_ci='%.3f-%.3f'%wil(o['k'],o['n']),newcombe='%.3f to %.3f'%newc(w['k'],w['n'],o['k'],o['n']),fisher_p=p,
   with_cost=w['cost'],without_cost=o['cost'],with_wall=w['wall'],without_wall=o['wall'],
   route_match=w['routes']==o['routes'] and len(w['routes'])==1,routes='|'.join(map(str,w['routes']|o['routes'])),
   bcs_with='|'.join(w['src']),bcs_without='|'.join(o['src'])))
ps=sorted([(r['fisher_p'],i) for i,r in enumerate(rows) if 'fisher_p' in r]);m=len(ps);run=0
for j,(p,i) in enumerate(ps): run=max(run,min(1,(m-j)*p));rows[i]['holm_p']=run
with open('score.csv','w') as f:
  wr=csv.DictWriter(f,fieldnames=list(rows[0].keys())+['holm_p']);wr.writeheader();[wr.writerow(r) for r in rows]
for r in rows: print({k:(round(v,4) if isinstance(v,float) else v) for k,v in r.items()})
print('cells',allcells,'scored cost',round(tot,2),'gate cost',round(gtot,2),'sum+2.08',round(tot+gtot+2.08,2))
print('incomplete',comp['incomplete'],'untagged',comp['untagged_rerun_cells'])
print('models',{s:v['models'] for s,v in sides.items() if s.startswith('3481')}, set().union(*[v['models'] for v in sides.values()]))
print('fc',{s:dict(v['fc']) for s,v in sides.items()})
print('old complete',{k:v.get('on_route') for k,v in old['complete'].items()},old.get('incomplete') and {k:(v if not isinstance(v,dict) else {kk:vv for kk,vv in v.items() if kk!='cells'}) for k,v in old['incomplete'].items()})
print('issues',len(issues));[print(' ',i) for i in issues[:40]]
