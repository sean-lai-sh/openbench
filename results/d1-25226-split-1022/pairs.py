# Per-pair comparison: each variant vs its own row's 30 base (without) cells. Computed from <pr>/{without,with}.jsonl + transcripts; no hand-entered numbers.
import json,glob,re
from math import comb
D='/workspace/openbench-ab/results/d1-25226-split-1022'
def fisher(a,n1,c,n2):
  K=a+c;N=n1+n2;p=lambda x:comb(n1,x)*comb(n2,K-x)/comb(N,K);p0=p(a)
  return sum(p(x) for x in range(max(0,K-n2),min(K,n1)+1) if p(x)<=p0*(1+1e-9))
def arm(pr,side):
  c=dict(n=0,solved=0,mktemp=0,opencode=0,leaked=0,scratch_left=0,rejections=0)
  for l in open(f'{D}/{pr}/{side}.jsonl'):
    r=json.loads(l)
    if (r.get('failure_class') or '')=='infra': continue
    c['n']+=1; c['solved']+=bool(r.get('success'))
    c['leaked']+=int(r.get('tmpdir_leaked_dirs') or 0)>0; c['scratch_left']+=int(r.get('scratch_dirs_left') or 0)>0
    c['rejections']+=int(r.get('permission_rejections') or 0)>0
    fs=glob.glob(f"{D}/{pr}/transcripts/{side}/*trial{r['trial']}.txt")
    if fs:
      t=open(fs[0],errors='ignore').read()
      cmds=re.findall(r'permission=bash pattern=(.*?) ruleset=',t); ext=re.findall(r'permission=external_directory pattern=(\S+)',t)
      c['mktemp']+=any(x.startswith('mktemp') for x in cmds); c['opencode']+=any('/opencode' in x for x in cmds+ext)
  return c
K=['solved','mktemp','opencode','leaked','scratch_left','rejections']
print('pair | measure | own base | variant | Fisher p (two-sided)'); print('---|---|---|---|---')
for pr,name in (('925226','PERM-only'),('825226','PROMPT-only')):
  b,v=arm(pr,'without'),arm(pr,'with')
  for k in K: print(f"{name} ({pr}) | {k} | {b[k]}/{b['n']} | {v[k]}/{v['n']} | {fisher(v[k],v['n'],b[k],b['n']):.3g}")
