# usage: setaside7.py <out-dir>: SETASIDE-infra.txt (excluded), SETASIDE-stalls.txt (timeout/hang cells, kept in stats as fails), SETASIDE-quarantine.txt
import json,glob,sys,datetime as dt
D=sys.argv[1]; EX=("infra","rate_limited","stalled","incompatible"); inf=[];st=[]
def et(s):
  try: return dt.datetime.fromisoformat(str(s).replace('Z','+00:00')).astimezone(dt.timezone(dt.timedelta(hours=-4))).strftime('%m-%d %H:%M ET')
  except Exception: return str(s)
for p in sorted(glob.glob(f'{D}/*/cells/*/*/*.json')):
  r=json.load(open(p)); a=p[len(D)+1:].split('/'); fc=r.get('failure_class')
  ln=f"{a[0]} {a[2]} {a[3]} trial {a[4][:-5]} {fc} {str(r.get('error') or r.get('failure_reason')).replace(chr(10),' ')[:120]} {et(r.get('started_at') or r.get('ts_iso'))}"
  if fc in EX: inf.append(ln+' | excluded (infra)')
  elif fc in ('timeout','hang'): st.append(ln+' | kept as fail (hang)')
open(f'{D}/SETASIDE-infra.txt','w').write(f'# {len(inf)} infra cells, excluded from stats\n'+'\n'.join(inf)+'\n')
open(f'{D}/SETASIDE-stalls.txt','w').write(f'# {len(st)} stall/hang cells (300 s cell timeout), counted as fails\n'+'\n'.join(st)+'\n')
open(f'{D}/SETASIDE-quarantine.txt','w').write('# no quarantined cells\n')
print(len(inf),len(st))
