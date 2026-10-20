# usage: trigger7.py <out-dir>: per row/side, how many scored cells show the trigger firing (task DETECTORS.md "exercised" rules, simplified to cell fields + transcript grep).
import json,glob,sys,re,os
D=sys.argv[1]; EX=("infra","rate_limited","stalled","incompatible")
def tr(row,side,task,t):
  p=f"{D}/{row}/transcripts/{side}/omp_{task}_claude-opus-5-5_trial{t}.txt"; return open(p,errors='ignore').read() if os.path.exists(p) else ''
RULE={'trig-omp-fanout':('task tool call (subagent spawn)',lambda r,x:(r.get('task_calls') or 0)>0 or '"toolName":"task"' in x),
 'trig-omp-image':('read of assets/spec.png',lambda r,x:bool(re.search(r'"toolName":"read"[^\n]{0,400}spec\.png',x))),
 'trig-omp-mdtable':('hashline read of docs/limits.md + edit',lambda r,x:'limits.md' in x and (r.get('edit_calls') or 0)>0),
 'trig-omp-callsites':('content search for legacy_fetch',lambda r,x:bool(re.search(r'"toolName":"(grep|search|bash)"[^\n]{0,400}legacy_fetch',x))),
 'trig-omp-netclient':('always-on prompt rule',None),'trig-omp-experiment':('always-on prompt rule',None)}
for rd in sorted(glob.glob(f'{D}/omp-*')):
  row=os.path.basename(rd); out=[]
  for side in ('without','with'):
    fs=glob.glob(f'{rd}/cells/{side}/*/*.json'); n=f=0; task=''
    for p in fs:
      r=json.load(open(p)); task=p.split('/')[-2]
      if r.get('failure_class') in EX: continue
      n+=1; name,fn=RULE.get(task,('?',None)); f+= 1 if fn is None else int(bool(fn(r,tr(row,side,task,os.path.basename(p)[:-5]))))
    out.append(f"{side} {f}/{n}")
  name=RULE.get(task,('?',None))[0]
  print(f"{row} {task}: trigger = {name}: {'; '.join(out)}")
