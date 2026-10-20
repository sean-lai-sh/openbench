# Pilot selection (step 8, 447-PR Sonnet run, pilot only). Deterministic rule, logged in SELECTION.txt.
import csv,hashlib,random,re,os,json
B='/workspace/thesis-research/briefs'; T='/tmp/ob-s6run/tasks'
rows=list(csv.DictReader(open(f'{B}/opencode-harness-prs-full.csv')))
inc=[r for r in rows if r['included']=='yes']
ex34=sorted([r for r in inc if r['in_earlier_34']=='yes'],key=lambda r:int(r['pr']))
rest=sorted([r for r in inc if r['in_earlier_34']!='yes'],key=lambda r:int(r['pr']))
tasks=sorted(os.listdir(T))
def task_of(r):
  if r['exercisable']=='needs-new-task': return None
  f=r['trigger_task']
  m=[t for t in tasks if re.search(r'(?<![\w-])'+re.escape(t)+r'(?![\w-])',f)]
  return m[0] if len(m)==1 else None
elig=[r for r in rest if task_of(r)]
pick=sorted(random.Random(1016).sample(elig,10),key=lambda r:int(r['pr']))
H=lambda s:hashlib.sha256(s.encode()).hexdigest()
L34='\n'.join(r['pr'] for r in ex34)+'\n'; L413='\n'.join(r['pr'] for r in rest)+'\n'
open('excluded-34.txt','w').write(L34); open('scope-413.txt','w').write(L413)
with open('SELECTION.txt','w') as o:
  o.write(f"source opencode-harness-prs-full.csv sha256 {hashlib.sha256(open(f'{B}/opencode-harness-prs-full.csv','rb').read()).hexdigest()}\n")
  o.write(f"opus-check-sample.csv sha256 {hashlib.sha256(open(f'{B}/opus-check-sample.csv','rb').read()).hexdigest()} (expected prefix f6a180f4: {'OK' if hashlib.sha256(open(f'{B}/opus-check-sample.csv','rb').read()).hexdigest().startswith('f6a180f4') else 'MISMATCH'})\n")
  o.write(f"included=yes: {len(inc)}; in_earlier_34=yes: {len(ex34)} (excluded-34.txt sha256 {H(L34)}); scope: {len(rest)} (scope-413.txt sha256 {H(L413)}; one PR number per line, ascending)\n")
  o.write("Rule: from the scope, drop exercisable=needs-new-task and rows whose trigger_task field does not name exactly one existing task dir in runner tasks/ (12393ffd8); eligible sorted by PR number ascending; random.Random(1016).sample(eligible, 10); pick sorted by PR.\n")
  o.write(f"eligible: {len(elig)}\npick:\n"+''.join(f"  {r['pr']} {task_of(r)} {r['exercisable']} {r['category']} | {r['title'][:70]}\n" for r in pick))
with open('pilot-prs.csv','w',newline='') as f:
  w=csv.writer(f); w.writerow(['#','PR','Title','Merged','Merge commit SHA','Parent/base SHA','Nearest release tag','Category','Files changed','Key paths','One-line behavior change','Harness change','Bug-fix check'])
  for i,r in enumerate(pick,1): w.writerow([i,r['pr'],r['title'],r['merged'],r['merge_sha'],r['parent_sha'],'',r['category'],'',r['harness_files'],r['description'][:200],'',''])
with open('pilot-task-map.csv','w',newline='') as f:
  w=csv.writer(f); w.writerow(['pr','task','status','options'])
  for r in pick: w.writerow([r['pr'],task_of(r),'triggerable',''])
