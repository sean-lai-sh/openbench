# usage: tc400.py <out-dir>...: per row, tool_choice-400 set-aside cells per side; flags 'set-aside imbalance across sides' if one side has >=2x the other (and >=3 cells on the heavier side; smaller counts are treated as noise).
import json,glob,sys,os
for D in sys.argv[1:]:
  for rd in sorted(glob.glob(f'{D}/omp-*')):
    c={}
    for s in ('without','with'):
      c[s]=sum('tool_choice' in str(json.load(open(p)).get('error') or '') for p in glob.glob(f'{rd}/cells/{s}/*/*.json'))
    if sum(c.values())==0: continue
    a,b=c['without'],c['with']; f=' -> set-aside imbalance across sides' if max(a,b)>=3 and max(a,b)>=2*max(min(a,b),1) else ''
    print(f"{os.path.basename(D)} {os.path.basename(rd)}: tool_choice-400 set-aside w/o={a} with={b}{f}")
