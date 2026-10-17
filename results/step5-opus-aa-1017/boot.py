import json,glob,sys,random
def tok(r): return sum((r.get(k) or 0) for k in ("tokens_input_uncached","tokens_output","tokens_cache_read","tokens_cache_write"))
def side(d,s,drop=("infra","hang","rate_limited","stalled")):
    rs=[json.load(open(p)) for p in glob.glob(f"{d}/cells/{s}/*/*.json")]
    return [tok(r) for r in rs if r.get("failure_class") not in drop]
def boot(a,b,n=10000,seed=0):
    rnd=random.Random(seed); m=lambda x:sum(x)/len(x); out=[]
    for _ in range(n):
        out.append(m([rnd.choice(b) for _ in b])/m([rnd.choice(a) for _ in a])-1)
    out.sort(); return m(b)/m(a)-1,out[int(.025*n)],out[int(.975*n)-1]
if __name__=="__main__":
    d,a,b=sys.argv[1:4]; A,B=side(d,a),side(d,b)
    print(len(A),len(B),["%+.1f%%"%(100*x) for x in boot(A,B)])
