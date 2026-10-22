# D1 25226 split analysis (read-only over cells/transcripts/ledger). Arms: BASE = without side of both rows (33f7f593),
# PERM = 925226 with (c0a007ba), PROMPT = 825226 with (c436fc69). Reference: step3-sonnet-1016-make-rebuild2/25226 (without, full PR with).
import json,glob,re,collections,sys
from datetime import datetime
from math import comb
R='/workspace/openbench-ab/results'
def fisher(a,n1,c,n2):
  K=a+c;N=n1+n2;p=lambda x:comb(n1,x)*comb(n2,K-x)/comb(N,K);p0=p(a)
  return sum(p(x) for x in range(max(0,K-n2),min(K,n1)+1) if p(x)<=p0*(1+1e-9))
def cells(base,side):
  out={}
  for l in open(f'{base}/{side}.jsonl'):
    r=json.loads(l); out[int(r['trial'])]=r
  return out
def tcls(base,side,tr):
  fs=glob.glob(f'{base}/transcripts/{side}/*trial{tr}.txt')
  if not fs: return None
  t=open(fs[0],errors='ignore').read()
  cmds=re.findall(r'permission=bash pattern=(.*?) ruleset=',t)
  ext=re.findall(r'permission=external_directory pattern=(\S+)',t)
  return dict(mktemp=any(x.startswith('mktemp') for x in cmds),
              oc=any('/opencode' in x for x in cmds+ext) or any('$S' in x for x in cmds) and False)
arms=[('BASE(925226 row)',f'{R}/d1-25226-split-1022/925226','without'),('BASE(825226 row)',f'{R}/d1-25226-split-1022/825226','without'),
      ('PERM-only',f'{R}/d1-25226-split-1022/925226','with'),('PROMPT-only',f'{R}/d1-25226-split-1022/825226','with'),
      ('ref step3 without',f'{R}/step3-sonnet-1016-make-rebuild2/25226','without'),('ref step3 full-PR with',f'{R}/step3-sonnet-1016-make-rebuild2/25226','with')]
RATE=dict(inp=2,out=10,cr=0.1,cw=2.5)
res={}
print('arm | scored | infra | solved | mktemp | opencode/ used | leaked>0 | scratch_left>0 | combined left | perm_rej>0 | ended_on_rej | cells$')
for name,base,side in arms:
  cs=cells(base,side); c=collections.Counter(); cost=0
  for tr,r in cs.items():
    cost+=r.get('requests_cost_usd') or 0
    if (r.get('failure_class') or '')=='infra': c['infra']+=1; continue
    c['n']+=1; c['solved']+=bool(r.get('success'))
    L=int(r.get('tmpdir_leaked_dirs') or 0)>0; S=int(r.get('scratch_dirs_left') or 0)>0
    c['leak']+=L; c['scr']+=S; c['comb']+=L or S
    c['rej']+=int(r.get('permission_rejections') or 0)>0; c['end']+=bool(r.get('ended_on_rejection'))
    k=tcls(base,side,tr)
    if k: c['mk']+=k['mktemp']; c['oc']+=k['oc']
  res[name]=c
  print(f"{name} | {c['n']} | {c['infra']} | {c['solved']}/{c['n']} | {c['mk']} | {c['oc']} | {c['leak']} | {c['scr']} | {c['comb']} | {c['rej']} | {c['end']} | ${cost:.2f}")
b={k:res['BASE(925226 row)'][k]+res['BASE(825226 row)'][k] for k in ['n','solved','mk','oc','leak','scr','comb','rej','end']}
print('BASE pooled',b)
for arm in ['PERM-only','PROMPT-only','ref step3 full-PR with']:
  a=res[arm]
  for k in ['mk','oc','leak','comb','rej','solved']:
    print(f'  {arm} vs BASE pooled {k}: {a[k]}/{a["n"]} vs {b[k]}/{b["n"]} p={fisher(a[k],a["n"],b[k],b["n"]):.3g}')
# ledger cost (Sonnet rates = half Opus RATES)
tot=0;n=0;models=collections.Counter()
for f in glob.glob(f'{R}/d1-25226-split-1022*/proxy-ledger/*.jsonl'):
  for l in open(f):
    r=json.loads(l)
    if r.get('record_type')!='request': continue
    u=r.get('usage') or {}; models[r.get('upstream_model')]+=1; n+=1
    tot+=(u.get('input_tokens',0)*RATE['inp']+u.get('output_tokens',0)*RATE['out']+u.get('cache_read_input_tokens',0)*RATE['cr']+u.get('cache_creation_input_tokens',0)*RATE['cw'])/1e6
print(f'ledger (smoke+full): {n} requests, models {dict(models)}, cost ${tot:.2f}')
