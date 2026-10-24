import json,sys,urllib.request,pathlib
from thesis.ab.vertex_anthropic_proxy import start_from_env, cell_proxy_base
out=pathlib.Path(sys.argv[1]); led=out/"proxy-ledger"; led.mkdir(parents=True,exist_ok=True)
p=start_from_env(ledger_dir=led, model="claude-sonnet-5-5")
base=p.base_url; print("base",base)
res={}
def post(cell,path,body,hdr={}):
    url=cell_proxy_base(base,cell).rstrip("/")
    if not url.endswith("/v1"): url+="/v1"
    r=urllib.request.Request(url+path,data=json.dumps(body).encode(),headers={"content-type":"application/json","x-api-key":"proxy","authorization":"Bearer proxy","anthropic-version":"2023-06-01",**hdr})
    with urllib.request.urlopen(r,timeout=120) as f: return f.status,f.read().decode()
M={"role":"user","content":"Reply with exactly: PONG"}
cases=[("smoke-anth","/messages",{"model":"claude-sonnet-5-5","max_tokens":64,"messages":[M]},{"X-OB-Call-Role":"main"}),
 ("smoke-anth","/messages",{"model":"claude-sonnet-5-5","max_tokens":64,"stream":True,"messages":[M]},{"X-OB-Call-Role":"side:title"}),
 ("smoke-oai","/chat/completions",{"model":"claude-sonnet-5-5","max_tokens":64,"messages":[M]},{"X-OB-Call-Role":"main"}),
 ("smoke-oai","/chat/completions",{"model":"claude-sonnet-5-5","max_tokens":64,"stream":True,"stream_options":{"include_usage":True},"messages":[M]},{})]
ok=True
for i,(c,pth,b,h) in enumerate(cases):
    try:
        s,t=post(c,pth,b,h); good=(s==200 and "PONG" in t); 
    except Exception as e: s,t,good=-1,repr(e),False
    ok&=good; print(f"case{i} {c}{pth} stream={b.get('stream',False)} status={s} PONG={good}\n  {t[:600]}")
for f in sorted(led.glob("*")): print("==",f.name); print(f.read_text()[:2000])
print("API_SMOKE", "PASS" if ok else "FAIL")
