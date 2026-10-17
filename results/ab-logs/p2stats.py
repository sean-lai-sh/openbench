import json,glob,sys,statistics as st,os,shutil
sys.path.insert(0,'/workspace/openbench-ab')
from thesis.ab.summarize import row_cost
def rows(pr,side):
    out=[]
    for p in glob.glob(f'results/ab/{pr}/cells/{side}/*/*.json'):
        try: out.append(json.load(open(p)))
        except Exception: pass
    return out
def total():
    t=0.0
    for p in glob.glob('results/ab/*/cells/*/*/*.json'):
        try: c=row_cost(json.load(open(p)))
        except Exception: c=None
        t+=c or 0
    return t
def quarantine(pr):
    moved=[]
    for p in glob.glob(f'results/ab/{pr}/cells/*/*/*.json'):
        d=json.load(open(p))
        if d.get('failure_class')=='infra' and 'Traceback' in str(d.get('error') or ''):
            dest=p.replace('results/ab/','results/ab-quarantine/phase2/',1)
            os.makedirs(os.path.dirname(dest),exist_ok=True); shutil.move(p,dest); moved.append((p,str(d['error']).strip().splitlines()[-1][:200]))
    return moved
def line(pr):
    cells=[]
    for side in ['without','with']:
        r=rows(pr,side)
        inc=f'results/ab/{pr}/{side}.incompatible.json'
        if os.path.exists(inc):
            cells.append(f'{side}: INCOMPATIBLE ({json.load(open(inc))["reason"][:150]})'); continue
        if not r: cells.append(f'{side}: no cells'); continue
        f=lambda k:[x[k] for x in r if x.get(k) is not None]
        m=lambda l: f'{st.mean(l):.1f}' if l else 'n/a'
        tok=[(x.get('tokens_input_uncached') or 0)+(x.get('tokens_output') or 0)+(x.get('tokens_cache_read') or 0)+(x.get('tokens_cache_write') or 0) for x in r if x.get('tokens_output') is not None]
        costs=[row_cost(x) for x in r]; mc=[c for c in costs if c is not None]
        unm=len(costs)-len(mc)
        fc={}
        for x in r: fc[x.get('failure_class')]=fc.get(x.get('failure_class'),0)+1
        cells.append(f'{side}: n={len(r)} pass={sum(1 for x in r if x.get("success"))/len(r):.3f} wall={m(f("wall_time_s"))}s turns={m(f("turns"))} tok/cell={m(tok)} cost/cell=${(st.mean(mc) if mc else 0):.3f} classes={fc}'+(f' UNMETERED={unm}' if unm else ''))
    return cells
if __name__=='__main__':
    cmd=sys.argv[1]
    if cmd=='total': print(f'{total():.2f}')
    elif cmd=='quarantine':
        for m in quarantine(sys.argv[2]): print('QUARANTINED',*m)
    elif cmd=='progress':
        pr,status=sys.argv[2],sys.argv[3]
        with open('results/ab-logs/phase2-progress.md','a') as fh:
            fh.write(f'\n## PR {pr} ({status})\n')
            for c in line(pr): fh.write(f'- {c}\n')
            fh.write(f'- cumulative spend (all phases, est.): ${total():.2f}\n')
