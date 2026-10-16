import json,glob,sys,collections
for d in sorted(glob.glob('/workspace/openbench-ab/results/smoke-1016/*/')):
    ups=collections.Counter(json.loads(l).get('upstream_model') for f in glob.glob(d+'proxy-ledger/*.jsonl') for l in open(f))
    for f in sorted(glob.glob(d+'*/*.jsonl')):
        for l in open(f):
            r=json.loads(l); tok=sum((r.get(k) or 0) for k in ['requests_input_uncached','requests_output','requests_cache_read','requests_cache_write'])
            print(d.split('/')[-2], f.split('/')[-1][:-6], r.get('failure_class'), 'success=',r.get('success'), 'tok=',tok, 'out=',r.get('requests_output'),'req=',r.get('requests_count'), 'cost=$%.3f'%(r.get('requests_cost_usd') or 0), 'think=',r.get('thinking_mode'), 'err=',(r.get('error') or r.get('failure_reason') or '')[:150], dict(ups))
