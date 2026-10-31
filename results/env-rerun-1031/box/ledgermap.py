import json,glob,os,sys,datetime
B=sys.argv[1]
def fp_row(r): return (r.get('tokens_proxy_cache_read'),r.get('tokens_proxy_cache_write'),r.get('tokens_proxy_input_uncached'),r.get('tokens_proxy_output'),r.get('tokens_proxy_calls'))
def fp_tot(t): a=t.get('all',{}); return (a.get('cache_read'),a.get('cache_write'),a.get('input_uncached'),a.get('output'),a.get('calls'))
rows={f.replace(B+'/',''):json.load(open(f)) for f in glob.glob(B+'/*/*/cells/*/*/*.json')}
used={}
for lf in sorted(glob.glob(B+'/*/proxy-ledger/*.jsonl')):
    arm=lf.split('/')[-3]; t=json.load(open(lf[:-6]+'.totals.json')) if os.path.exists(lf[:-6]+'.totals.json') else {}
    m=[k for k,r in rows.items() if k.startswith(arm+'/') and fp_row(r)==fp_tot(t)]
    req=[json.loads(l) for l in open(lf) if l.strip()]
    la=sorted(set(str(x.get('loaded_anthropic')) for x in req if x.get('record_type')=='request'))
    mt=datetime.datetime.fromtimestamp(os.path.getmtime(lf)).strftime('%H:%M:%S')
    dt=[round(abs(datetime.datetime.fromisoformat(rows[k]['ended_et']).timestamp()-os.path.getmtime(lf))) for k in m]
    print(os.path.basename(lf)[:16],arm,'fp=',fp_tot(t),'->',m or 'NO ROW (orphan: no row written)','dt_s',dt,'loaded',la,'mtime',mt)
    for k in m: used.setdefault(k,[]).append(lf)
for k in rows:
    if k not in used: print('ROW WITHOUT LEDGER',k)
for k,v in used.items():
    if len(v)>1: print('AMBIGUOUS',k,v)
