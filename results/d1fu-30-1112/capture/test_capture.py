# Offline check: patched proxy against a dummy upstream; asserts proxy output unchanged and files written.
import json, os, sys, threading, urllib.request, tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
tmp = tempfile.mkdtemp(); sys.argv = ["x", "--out", tmp]
import runpy
ns = runpy.run_path("/o/capture_run_ab.py", run_name="capwrap")  # load funcs without patching
import thesis.ab.vertex_anthropic_proxy as v
os.makedirs(os.path.join(tmp, "request-bodies"), exist_ok=True)
got = []
class Up(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers["Content-Length"]); got.append(self.rfile.read(n))
        b = json.dumps({"id":"m","type":"message","role":"assistant","content":[{"type":"text","text":"hi"}],"model":"x","stop_reason":"end_turn","usage":{"input_tokens":1,"output_tokens":1}}).encode()
        self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b)
    def log_message(self,*a): pass
up = ThreadingHTTPServer(("127.0.0.1",0),Up); threading.Thread(target=up.serve_forever,daemon=True).start()
body = json.dumps({"model":"claude-sonnet-5-5","max_tokens":10,"system":"s","messages":[{"role":"user","content":"hello"}]}).encode()
def call(px):
    r = urllib.request.Request(px.base_url.rstrip("/") + "/c/testcell/v1/messages", data=body, headers={"Content-Type":"application/json"}, method="POST")
    return urllib.request.urlopen(r).read()
led = os.path.join(tmp, "led"); os.makedirs(led)
px = v.start_proxy("p", model="claude-sonnet-5-5", token="t", upstream="http://127.0.0.1:%d" % up.server_port, ledger_dir=led)
r1 = call(px); px.stop() if hasattr(px,"stop") else None
v.split_cell_path = ns["split_cell_path"]; v.classify_call_role = ns["classify_call_role"]; v.translate_body = ns["translate_body"]
px2 = v.start_proxy("p", model="claude-sonnet-5-5", token="t", upstream="http://127.0.0.1:%d" % up.server_port, ledger_dir=led)
r2 = call(px2)
assert got[0] == got[1], "upstream bytes changed"
assert r1 == r2
d = os.path.join(tmp, "request-bodies", "testcell")
print(sorted(os.listdir(d)))
m = json.loads(open(os.path.join(d,"meta.jsonl")).read())
assert open(os.path.join(d,"0001.forwarded.bin"),"rb").read() == got[1]
assert open(os.path.join(d,"0001.pre_translate.bin"),"rb").read() == body
print(json.dumps(m, indent=1)); print("errors:", os.path.exists(os.path.join(tmp,"request-bodies","errors.log")))
print("OK")
