# Step-8 M1 VM A/A analysis. tokens = requests_input_uncached+requests_output+requests_cache_read+requests_cache_write.
# Excluded from tokens/solved: failure_class in infra/hang/rate_limited/stalled/incompatible. Bootstrap 95% percentile CI, 10k resamples, rng seed 1016, (aa-2 - aa-1)/aa-1.
import json,glob,csv,random,sys,os
R=sys.argv[1]; EX={'infra','hang','rate_limited','stalled','incompatible'}
rows=[]
for f in sorted(glob.glob(f'{R}/run/26821/cells/*/*/*.json')):
    d=json.load(open(f)); side=f.split('/cells/')[1].split('/')[0]
    tok=sum((d.get(k) or 0) for k in ('requests_input_uncached','requests_output','requests_cache_read','requests_cache_write'))
    rows.append(dict(machine='thesis-h1-cpu',vm_type=d.get('vm_type') or os.environ.get('VMT','n2-standard-16'),side=side,trial=d.get('trial'),task=d.get('task'),
      failure_class=d.get('failure_class'),solved=d.get('failure_class')=='solved',tokens=tok,cost_usd=round(d.get('requests_cost_usd') or 0,4),
      upstream_model=d.get('upstream_model'),host=d.get('host'),run_seed=d.get('run_seed')))
with open(f'{R}/cells.csv','w',newline='') as o:
    w=csv.DictWriter(o,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
S={}
out=[]
for s in ('aa-1','aa-2'):
    r=[x for x in rows if x['side']==s]; j=[x for x in r if x['failure_class'] not in EX]
    S[s]=[x['tokens'] for x in j]
    cl={}; [cl.__setitem__(x['failure_class'],cl.get(x['failure_class'],0)+1) for x in r]
    out.append(f"{s}: n={len(r)} judged={len(j)} solved {sum(x['solved'] for x in j)}/{len(j)} classes {cl} tok mean {sum(S[s])/len(S[s]):.0f} cost ${sum(x['cost_usd'] for x in r):.2f}")
m=lambda a:sum(a)/len(a); a,b=S['aa-1'],S['aa-2']; pt=(m(b)-m(a))/m(a)*100
rng=random.Random(1016); bs=sorted((m(rng.choices(b,k=len(b)))-(ma:=m(rng.choices(a,k=len(a)))))/ma*100 for _ in range(10000))
lo,hi=bs[249],bs[9749]
out.append(f"diff aa-2 vs aa-1: {pt:+.1f}% bootstrap 95% CI [{lo:+.1f}%, {hi:+.1f}%]")
out.append(f"overlap with shared-bot Sonnet OpenCode A/A band +0.1% [-6.5, +6.8]: {'YES' if lo<=6.8 and hi>=-6.5 else 'NO'}")
out.append(f"total spend ${sum(x['cost_usd'] for x in rows):.2f} (cap $20)")
open(f'{R}/SUMMARY.txt','w').write('\n'.join(out)+'\n'); print('\n'.join(out))
