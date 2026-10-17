import json,glob,collections
from thesis.ab.run_ab import read_cell
import thesis.ab.run_ab as r
from thesis.ab.summarize import row_cost as rc
tot=0; c=collections.Counter(); per=collections.defaultdict(float); errs=[]
for p in glob.glob('results/ab/*/cells/*/*/*.json'):
    d=read_cell(__import__('pathlib').Path(p))
    if not d: continue
    parts=p.split('/'); pr,side=parts[2],parts[4]
    x=rc(d) or 0; tot+=x; per[(pr,side)]+=x
    c[(pr,side,d.get('failure_class'))]+=1
    if d.get('error'): errs.append((p,str(d.get('error'))[:200]))
print('total $%.2f'%tot)
for k in sorted(per): print(k, '$%.2f'%per[k])
for k in sorted(c): print(k,c[k])
for e in errs: print('ERR',e)
