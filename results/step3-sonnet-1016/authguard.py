# Watch an --out dir while run_ab runs. Kill the run's process group and write a stop flag when
# (a) >3 of any PR's first 10 cells (by started_at) are Vertex 401 / ADC-refresh failures, or
# (b) free disk on / drops under 5 GB.  usage: authguard.py OUT PGID STOPFLAG
import json,glob,os,sys,time,shutil,signal
OUT,PGID,STOP=sys.argv[1],int(sys.argv[2]),sys.argv[3]
PATS=("ADC refresh failed","invalid authentication credentials","UNAUTHENTICATED",'"code": 401','"statusCode":401','"statusCode": 401')
def authfail(p,r):
    s=json.dumps(r)
    if any(x in s for x in PATS): return True
    pr,_,side,task,f=p.rsplit('/',5)[-5:]
    t=os.path.join(OUT,pr,'transcripts',side,task,f[:-5],'agent-output.txt')
    try: s=open(t,errors='replace').read()
    except OSError: return False
    return any(x in s for x in PATS)
def alive():
    try: os.killpg(PGID,0); return True
    except OSError: return False
def stop(msg):
    open(STOP,'w').write(time.strftime('%F %T ')+msg+'\n'); print(msg,flush=True)
    try: os.killpg(PGID,signal.SIGTERM); time.sleep(20); os.killpg(PGID,signal.SIGKILL)
    except OSError: pass
    sys.exit(1)
while alive():
    free=shutil.disk_usage('/').free/1e9
    if free<5: stop(f"DISK-PAUSE: free {free:.1f} GB < 5 GB")
    for d in glob.glob(OUT+'/*/cells'):
        rows=[]
        for p in glob.glob(d+'/*/*/*.json'):
            try: r=json.load(open(p))
            except Exception: continue
            rows.append((str(r.get('started_at') or ''),p,r))
        head=sorted(rows)[:10]; n=sum(1 for _,p,r in head if authfail(p,r))
        if n>3: stop(f"AUTH-STOP: PR {d.split('/')[-2]}: {n} of first {len(head)} cells are 401/ADC-refresh failures")
    time.sleep(10)
