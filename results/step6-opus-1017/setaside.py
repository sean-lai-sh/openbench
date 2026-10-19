# PM Set-aside convention (2026-10-17 22:55 ET). usage: setaside.py <batch label e.g. C1>
# Writes step6-opus-1017-<L>/SETASIDE-stalls.txt (infra/stalled/rate_limited/incompatible cells, excluded from stats; plus hang cells, which stay in stats as fails)
# and SETASIDE-quarantine.txt (cells moved to step6-opus-1017-quarantine/<L>, re-run, not used).
import json,glob,sys,os
from datetime import datetime
from zoneinfo import ZoneInfo
et=lambda t: datetime.fromisoformat(t).astimezone(ZoneInfo('America/New_York')).strftime('%Y-%m-%d %H:%M:%S ET') if t else '-'
RES='/workspace/openbench-ab/results'; L=sys.argv[1]; D=f'{RES}/step6-opus-1017-{L}'; Q=f'{RES}/step6-opus-1017-quarantine/{L}'
EX=("infra","rate_limited","stalled","incompatible")
out=["# pr side task trial failure_class infra_reason/error started_at(ET) | excluded-from-stats?"]
for p in sorted(glob.glob(f'{D}/*/cells/*/*/*.json')):
    r=json.load(open(p)); fc=r.get('failure_class')
    if fc in EX or fc=='hang':
        pr,_,side,task,f=p.rsplit('/',5)[-5:]
        out.append(f"{pr} {side} {task} {f[:-5]} {fc} {r.get('infra_reason') or str(r.get('error')).replace(chr(10),' ')[:120]} {et(r.get('started_at'))} | {'excluded (infra)' if fc in EX else 'kept as fail (hang)'}")
open(f'{D}/SETASIDE-stalls.txt','w').write('\n'.join(out)+'\n')
q=["# quarantined cells: path under step6-opus-1017-quarantine/"+L+" (reason in step6-opus-1017-quarantine/README.txt). Re-run in the batch dir; not used."]
q+= [os.path.relpath(p,Q) for p in sorted(glob.glob(f'{Q}/*/cells/*/*/*.json'))] if os.path.isdir(Q) else []
if len(q)==1: q.append("none")
open(f'{D}/SETASIDE-quarantine.txt','w').write('\n'.join(q)+'\n')
print(open(f'{D}/SETASIDE-stalls.txt').read()+open(f'{D}/SETASIDE-quarantine.txt').read())
