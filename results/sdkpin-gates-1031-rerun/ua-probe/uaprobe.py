import json, os, sys, subprocess, threading, urllib.request, http.server, time
from pathlib import Path
sys.path.insert(0, "/ob")
from thesis.ab.vertex_anthropic_proxy import start_from_env, cell_proxy_base
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
pins = sys.argv[2:]
px = start_from_env(ledger_dir=out / "proxy-ledger", model="claude-opus-5-5")
log = open(out / "raw_headers.jsonl", "a")
state = {}
class Tee(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        rec = {"pin": state["pin"], "path": self.path, "ts": time.strftime("%F %T %Z"),
               "headers": {k: v for k, v in self.headers.items() if k.lower() not in ("x-api-key", "authorization")}}
        log.write(json.dumps(rec) + "\n"); log.flush()
        url = cell_proxy_base(px.base_url, "uaprobe-" + state["pin"]) + self.path
        fwd = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "content-length")}
        req = urllib.request.Request(url, data=body, headers=fwd, method="POST")
        try: r = urllib.request.urlopen(req, timeout=120); code, data = r.status, r.read()
        except urllib.error.HTTPError as e: code, data = e.code, e.read()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Tee)
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]
bun = "/h1/opencode-src/bun/1.3.13/bun-linux-x64/bun"
for pin in pins:
    state["pin"] = pin
    pkg = f"/h1/opencode-src/provider-pins/{pin}/node_modules/@ai-sdk/anthropic/dist/index.mjs"
    js = f"""import {{ createAnthropic }} from '{pkg}';
const m = createAnthropic({{ baseURL: 'http://127.0.0.1:{port}/v1', apiKey: 'probe' }})('claude-opus-5-5');
const r = await m.doGenerate({{ prompt: [{{ role: 'user', content: [{{ type: 'text', text: 'Reply with OK.' }}] }}], maxOutputTokens: 8 }});
console.log(JSON.stringify({{ text: r.content ?? r.text, usage: r.usage }}));"""
    p = out / f"probe-{pin}.mjs"; p.write_text(js)
    res = subprocess.run([bun, str(p)], capture_output=True, text=True, timeout=180)
    (out / f"probe-{pin}.out").write_text(res.stdout + "\n--stderr--\n" + res.stderr[-3000:])
    print(pin, res.returncode, res.stdout[-300:], res.stderr[-300:])
