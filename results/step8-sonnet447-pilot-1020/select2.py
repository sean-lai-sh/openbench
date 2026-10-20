# Pilot selection v2 (PM 2026-10-20 00:31 ET): seeded stratified draw from the 413 by exercisable type.
import csv,hashlib,random,re,os
B='/workspace/thesis-research/briefs'; T='/tmp/ob-s6run/tasks'; SEED=20261020; N=10
rows=list(csv.DictReader(open(f'{B}/opencode-harness-prs-full.csv')))
inc=[r for r in rows if r['included']=='yes']
ex34=sorted([r for r in inc if r['in_earlier_34']=='yes'],key=lambda r:int(r['pr']))
rest=sorted([r for r in inc if r['in_earlier_34']!='yes'],key=lambda r:int(r['pr']))
tasks=sorted(os.listdir(T))
def task_of(r):
  for f in (r['trigger_task'],r['new_task_spec']):
    m=[t for t in tasks if re.search(r'(?<![\w-])'+re.escape(t)+r'(?![\w-])',f or '')]
    if len(set(m))==1: return m[0]
  return None
types=['always-on','conditional','needs-new-task']
G={t:[r for r in rest if r['exercisable']==t] for t in types}
# proportional allocation (largest remainder), at least 1 per type
q={t:N*len(G[t])/len(rest) for t in types}; k={t:max(1,int(q[t])) for t in types}
for t in sorted(types,key=lambda t:-(q[t]-int(q[t]))):
  if sum(k.values())<N: k[t]+=1
rnd=random.Random(SEED); pick=[]
for t in types: pick+= [(t,r) for r in rnd.sample(G[t],k[t])]
H=lambda s:hashlib.sha256(s.encode()).hexdigest()
L34='\n'.join(r['pr'] for r in ex34)+'\n'; L413='\n'.join(r['pr'] for r in rest)+'\n'
open('excluded-34.txt','w').write(L34); open('scope-413.txt','w').write(L413)
osh=hashlib.sha256(open(f'{B}/opus-check-sample.csv','rb').read()).hexdigest()
run=[(t,r) for t,r in pick if task_of(r)]; skip=[(t,r) for t,r in pick if not task_of(r)]
with open('SELECTION.txt','w') as o:
  o.write(f"source opencode-harness-prs-full.csv sha256 {hashlib.sha256(open(f'{B}/opencode-harness-prs-full.csv','rb').read()).hexdigest()}\n")
  o.write(f"opus-check-sample.csv sha256 {osh} (expected prefix f6a180f4: {'OK' if osh.startswith('f6a180f4') else 'MISMATCH'})\n")
  o.write(f"included=yes: {len(inc)}; in_earlier_34=yes: {len(ex34)} (excluded-34.txt sha256 {H(L34)}); scope: {len(rest)} (scope-413.txt sha256 {H(L413)}; one PR per line, ascending)\n")
  o.write(f"Rule v2: seed {SEED}; types in scope {dict((t,len(G[t])) for t in types)}; proportional allocation of {N} by largest remainder, min 1 per type -> {k}; per type in order {types}: random.Random({SEED}) (one generator, sequential) .sample(type rows sorted by PR, k). Task = the one existing runner task dir (12393ffd8 tasks/) named in trigger_task, else in new_task_spec; none -> skipped (logged).\n")
  o.write("draw:\n"+''.join(f"  {r['pr']} {t} {task_of(r) or 'SKIPPED: no runnable task'} {r['category']} | {r['title'][:70]}\n" for t,r in pick))
  o.write(f"to run: {len(run)}; skipped: {len(skip)}\n")
  o.write("Draw v1 (deterministic rule, seed 1016; replaced): see draw-v1/. Its smoke was stopped at 00:31 ET; 6 cells done (1761, 2466, 5298 one per side, \$1.23) kept as extras in step8-sonnet447-pilot-1020-smoke-v1-extras/ and counted toward the \$150 cap.\n")
with open('pilot-prs.csv','w',newline='') as f:
  w=csv.writer(f); w.writerow(['#','PR','Title','Merged','Merge commit SHA','Parent/base SHA','Nearest release tag','Category','Files changed','Key paths','One-line behavior change','Harness change','Bug-fix check'])
  for i,(t,r) in enumerate(run,1): w.writerow([i,r['pr'],r['title'],r['merged'],r['merge_sha'],r['parent_sha'],'',r['category'],'',r['harness_files'],r['description'][:200],'',''])
with open('pilot-task-map.csv','w',newline='') as f:
  w=csv.writer(f); w.writerow(['pr','task','status','options'])
  for t,r in run: w.writerow([r['pr'],task_of(r),'triggerable',''])
