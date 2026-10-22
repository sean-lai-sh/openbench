# Step-8 full run list (Sean OK 2026-10-20 12:04 ET). Scope = step8-sonnet447-pilot-1020/scope-413.txt; skip the 9 pilot PRs (done 30/side, #107) and PRs with no runnable task (same task rule as pilot select2.py).
import csv,re,os,hashlib
P='/workspace/openbench-ab/results/step8-sonnet447-pilot-1020'; B='/workspace/thesis-research/briefs'; T='/tmp/ob-s6run/tasks'
scope=[l.strip() for l in open(f'{P}/scope-413.txt') if l.strip()]
allr=[r for r in csv.DictReader(open(f'{B}/opencode-harness-prs-full.csv')) if r['included']=='yes' and r['in_earlier_34']!='yes']
rows={}
for r in sorted(allr,key=lambda r:r['title'].lower().startswith('revert')): rows.setdefault(r['pr'],r)  # one row per PR number: prefer the non-revert row
dup={r['pr']:r for r in allr if rows[r['pr']] is not r}
tasks=sorted(os.listdir(T))
def task_of(r):
  for f in (r['trigger_task'],r['new_task_spec']):
    m=[t for t in tasks if re.search(r'(?<![\w-])'+re.escape(t)+r'(?![\w-])',f or '')]
    if len(set(m))==1: return m[0]
  return None
pilot=[l.split(',')[0] for l in open(f'{P}/pilot-task-map.csv').read().split('\n')[1:] if l]
run=[];skip=[];seen=set()
for pr in scope:
  if pr in seen: skip.append((pr,f"duplicate PR number in inventory (second row merge {dup[pr]['merge_sha'][:10]}: {dup[pr]['title'][:50]!r}); runner keys by PR; non-revert row kept")); continue
  seen.add(pr)
  r=rows[pr]
  if pr in pilot: skip.append((pr,'pilot: done at 30/side (#107)')); continue
  t=task_of(r)
  if not t: skip.append((pr,f"Not run: no runnable task ({r['exercisable']}; trigger_task={r['trigger_task'][:60]!r})")); continue
  run.append((r,t))
with open('SKIPPED.txt','w') as o:
  o.write(f"# {len(skip)} of {len(scope)} scope PRs skipped\n"+''.join(f"{p} {why}\n" for p,why in skip))
with open('prs.csv','w',newline='') as f:
  w=csv.writer(f); w.writerow(['#','PR','Title','Merged','Merge commit SHA','Parent/base SHA','Nearest release tag','Category','Files changed','Key paths','One-line behavior change','Harness change','Bug-fix check'])
  for i,(r,t) in enumerate(run,1): w.writerow([i,r['pr'],r['title'],r['merged'],r['merge_sha'],r['parent_sha'],'',r['category'],'',r['harness_files'],r['description'][:200],'',''])
with open('task-map.csv','w',newline='') as f:
  w=csv.writer(f); w.writerow(['pr','task','status','options'])
  for r,t in run: w.writerow([r['pr'],t,'triggerable',''])
N=22; bs=[run[i:i+N] for i in range(0,len(run),N)]
with open('BATCHES.txt','w') as o:
  o.write(f"# {len(run)} PRs to run, scope order (PR ascending), batches of {N}; each batch run as sub-invocations of 11 PRs (disk check between)\n")
  for i,b in enumerate(bs,1): o.write(f"F{i:02d} "+','.join(r['pr'] for r,t in b)+"\n")
print(len(scope),len(skip),len(run),len(bs))
