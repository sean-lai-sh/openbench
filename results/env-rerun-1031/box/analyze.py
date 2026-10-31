import json,glob,os,csv,collections,datetime,sys
B='/workspace/env1031b'; OUT=sys.argv[1]
FOLDERS=[('VM1','env-rerun-1031b',B+'/vm1-copy/x/env-rerun-1031b','aborted_not_counted'),
 ('VM1','env-rerun-1031c',B+'/vm1-copy/x/env-rerun-1031c','counted'),
 ('VM1','env-rerun-1031d',B+'/vm1-copy/x/env-rerun-1031d','counted'),
 ('VM2','cells-rerun-1031',B+'/vm2-copy/cells-rerun-1031','aborted_not_counted'),
 ('VM2','cells-rerun-1031c',B+'/vm2-copy/cells-rerun-1031c','counted'),
 ('VM2','cells-smoke-1031d',B+'/vm2-copy/cells-smoke-1031d','counted'),
 ('VM2','cells-rerun-1031e',B+'/vm2-copy/cells-rerun-1031e','counted'),
 ('VM3','cells-rerun-1031c',B+'/vm3-copy/cells-rerun-1031c','counted')]
PIN={'3052':'2.0.25','13090':'2.0.58','13331':'2.0.58'}
def fp_row(r): return (r.get('tokens_proxy_cache_read'),r.get('tokens_proxy_cache_write'),r.get('tokens_proxy_input_uncached'),r.get('tokens_proxy_output'),r.get('tokens_proxy_calls'))
def fp_tot(t): a=t.get('all',{}); return (a.get('cache_read'),a.get('cache_write'),a.get('input_uncached'),a.get('output'),a.get('calls'))
lm={}
for r in csv.DictReader(open(B+'/datapr-draft/ledger_match.csv')):
    lm[(r['folder'].split()[1], r['row'])]=r['ledger']
allrows=[]; bf=[]
for vm,name,root,status in FOLDERS:
    rows={}
    for f in glob.glob(root+'/*/*/cells/*/*/*.json'):
        k=f[len(root)+1:]; rows[k]=json.load(open(f))
    led={}
    for lf in glob.glob(root+'/*/proxy-ledger/*.jsonl'):
        arm=lf.split('/')[-3]; tf=lf[:-6]+'.totals.json'
        t=json.load(open(tf)) if os.path.exists(tf) else {}
        req=[json.loads(l) for l in open(lf) if l.strip()]
        req=[x for x in req if x.get('record_type')=='request']
        led[os.path.basename(lf)[:-6]]=(arm,fp_tot(t),req,os.path.getmtime(lf))
    for k,d in sorted(rows.items()):
        m,pr,_,side,task,trial=k[:-5].split('/')
        short=f"{m} {side}/{task.replace('model-extraction-relu-logits','mx-relu').replace('torch-tensor-parallelism','torch-tensor')}/{trial}"
        cands=[i for i,(a,fp,_,_) in led.items() if a==m and fp==fp_row(d)]
        basis='fingerprint'
        forced=[i for i in led if lm.get((name,short),'~')!='~' and i.startswith(lm[(name,short)])]
        if forced: cands=forced; basis='token_cache_mtime'
        elif len(cands)>1:
            end=datetime.datetime.fromisoformat(d['ended_et']).timestamp()
            cands=[min(cands,key=lambda i:abs(led[i][3]-end))]; basis='token_cache_mtime(unlisted)'
        allrows.append(dict(vm=vm,run=name,run_status=status,model=m,pr=pr,side=side,task=task,trial=trial,outcome=d.get('failure_class'),
            env_cause=d.get('env_cause'),cost_usd=round(float(d.get('requests_cost_usd') or 0),4),wall_time_s=d.get('wall_time_s'),
            timeout_s=d.get('timeout_s'),checker_timeout_s=d.get('checker_timeout_s'),t_checker_s=d.get('t_checker_s'),
            failure_reason=(d.get('failure_reason') or '')[:160].replace('\n',' '),runner_commit=(d.get('runner_commit') or '')[:8],
            vm_name=d.get('vm_name'),loaded_anthropic=d.get('loaded_anthropic'),load_proof_basis_on_row=d.get('load_proof_basis')))
        if len(cands)!=1:
            bf.append(dict(vm=vm,run=name,model=m,pr=pr,side=side,task=task,trial=trial,pin=PIN.get(pr),ledger='',ledger_match_basis='none',n_requests=0,ua_versions='',load_proof_basis='',load_proof='',load_proof_reason='not backfilled: no unique ledger')); continue
        req=led[cands[0]][2]; vers=[str(x.get('loaded_anthropic') or '') for x in req]
        pin=PIN.get(pr)
        if not req or any(v in('','None') for v in vers):
            bf.append(dict(vm=vm,run=name,model=m,pr=pr,side=side,task=task,trial=trial,pin=pin,ledger=cands[0][:16],ledger_match_basis=basis,n_requests=len(req),ua_versions=';'.join(sorted(set(vers))),load_proof_basis='',load_proof='',load_proof_reason='not backfilled: a ledger request lacks UA loaded_anthropic' if req else 'not backfilled: no request records')); continue
        sv=sorted(set(vers)); ua=sv[0] if len(sv)==1 else 'mixed:'+','.join(sv)
        if ua.startswith('mixed:'): v,why='fail',f'User-Agent mixed versions {ua[6:]}'
        elif ua==pin: v,why='pass',f'User-Agent {ua}'
        else: v,why='fail',f'User-Agent {ua} != pin {pin}'
        bf.append(dict(vm=vm,run=name,model=m,pr=pr,side=side,task=task,trial=trial,pin=pin,ledger=cands[0][:16],ledger_match_basis=basis,n_requests=len(req),ua_versions=';'.join(sv),load_proof_basis='user_agent',load_proof=v,load_proof_reason=why))
def w(fn,rows):
    with open(OUT+'/'+fn,'w',newline='') as f:
        wr=csv.DictWriter(f,fieldnames=list(rows[0].keys())); wr.writeheader(); wr.writerows(rows)
w('rows-all.csv',allrows); w('load_proof_backfill.csv',bf)
w('hangs.csv',[r for r in allrows if r['outcome']=='hang'])
w('timeouts.csv',[r for r in allrows if r['outcome']=='timeout'])
w('infra.csv',[r for r in allrows if r['outcome']=='infra'])
c=collections.Counter((r['run'],r['run_status'],r['model'],r['pr'],r['outcome']) for r in allrows)
for k,v in sorted(c.items()): print(v,*k)
print(collections.Counter((b['run'],b['load_proof_basis'],b['load_proof'],b['ledger_match_basis']) for b in bf))
