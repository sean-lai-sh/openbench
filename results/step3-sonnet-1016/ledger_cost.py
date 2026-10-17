# Raw proxy-ledger spend for an A/B --out dir: every request record, priced by upstream_model
# (thesis.ab.summarize.RATES_BY_MODEL; cache writes at the 5-minute rate, 1h writes flagged).
import json,glob,sys
sys.path.insert(0,'/workspace/openbench-ab')
from thesis.ab.summarize import RATES_BY_MODEL, RATES
for d in sys.argv[1:]:
    tot=0; n=0; h1=0; models={}
    for p in glob.glob(d+'/proxy-ledger/*.jsonl'):
        for line in open(p):
            try: r=json.loads(line)
            except Exception: continue
            u=r.get('usage') or {}
            if not u: continue
            m=str(r.get('upstream_model') or '').split('@')[0]; rt=RATES_BY_MODEL.get(m,RATES)
            models[m]=models.get(m,0)+1
            h1+=(u.get('cache_creation') or {}).get('ephemeral_1h_input_tokens') or 0
            tot+=(u.get('input_tokens',0)*rt['tokens_input_uncached']+u.get('output_tokens',0)*rt['tokens_output']
                  +u.get('cache_read_input_tokens',0)*rt['tokens_cache_read']+u.get('cache_creation_input_tokens',0)*rt['tokens_cache_write'])/1e6
            n+=1
    print(f"{d}: ledger ${tot:.2f} over {n} usage records, models {models}, 1h-cache-write tokens {h1}")
