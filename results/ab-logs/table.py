import json,glob,sys,statistics as st,os
sys.path.insert(0,'/workspace/openbench-ab')
from thesis.ab.summarize import row_cost
def side(pr,s):
    r=[json.load(open(p)) for p in glob.glob(f'results/ab/{pr}/cells/{s}/*/*.json')]
    if not r: return None
    tok=[(x.get('tokens_input_uncached') or 0)+(x.get('tokens_output') or 0)+(x.get('tokens_cache_read') or 0)+(x.get('tokens_cache_write') or 0) for x in r if x.get('tokens_output') is not None]
    c=[row_cost(x) for x in r if row_cost(x) is not None]
    m=lambda l: st.mean(l) if l else float('nan')
    return dict(n=len(r),pass_=sum(1 for x in r if x.get('success'))/len(r),wall=m([x['wall_time_s'] for x in r if x.get('wall_time_s') is not None]),
        turns=m([x['turns'] for x in r if x.get('turns') is not None]),tok=m(tok),cost=m(c),sum=sum(c),unm=len(r)-len(c),
        cls={k:sum(1 for x in r if x.get('failure_class')==k) for k in set(x.get('failure_class') for x in r)})
pct=lambda a,b: (b-a)/a*100 if a else float('nan')
prs=sys.argv[1:]
print('| PR | n (b/a) | Pass b→a | Wall s b→a (Δ%) | Turns b→a | Tok/cell b→a (Δ%) | $/cell b→a (Δ%) | PR $ |')
print('|---|---|---|---|---|---|---|---|')
for pr in prs:
    b,a=side(pr,'without'),side(pr,'with')
    if not b or not a: print(f'| {pr} | missing side | | | | | | |'); continue
    print(f"| {pr} | {b['n']}/{a['n']} | {b['pass_']:.3f}→{a['pass_']:.3f} | {b['wall']:.1f}→{a['wall']:.1f} ({pct(b['wall'],a['wall']):+.1f}%) | {b['turns']:.1f}→{a['turns']:.1f} | {b['tok']/1e3:.0f}k→{a['tok']/1e3:.0f}k ({pct(b['tok'],a['tok']):+.1f}%) | {b['cost']:.3f}→{a['cost']:.3f} ({pct(b['cost'],a['cost']):+.1f}%) | {b['sum']+a['sum']:.2f} |"
          + (f" unmetered b={b['unm']} a={a['unm']}" if b['unm'] or a['unm'] else '') + (f" classes b={b['cls']} a={a['cls']}" if b['pass_']<1 or a['pass_']<1 else ''))
