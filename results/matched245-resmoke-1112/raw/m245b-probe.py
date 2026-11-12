#!/usr/bin/env python3
"""Opus 5.5 effort probe for PR #245 matched config. One minimal request per effort value,
lowest first, through the PR's Vertex proxy (OBENCH_MATCHED_CONFIG=1). Stops at the first 200."""
import json, os, sys, secrets, urllib.request, urllib.error
from pathlib import Path
OUT = Path(os.path.expanduser("~/h2/matched245-resmoke-1112/opus-effort-probe")); OUT.mkdir(parents=True, exist_ok=True)
os.environ["OBENCH_MATCHED_CONFIG"] = "1"
from thesis.ab import vertex_anthropic_proxy as vap
results = []
for effort in sys.argv[1:] or ["minimal", "low", "medium"]:
    os.environ["OBENCH_MATCHED_EFFORT"] = effort
    led = OUT / f"ledger-{effort}"; led.mkdir(exist_ok=True)
    os.environ["OBENCH_VERTEX_LEDGER_DIR"] = str(led)
    proxy = vap.start_from_env(ledger_dir=led, thinking_mode="default", model="claude-opus-5-5")
    cell = secrets.token_hex(8)
    body = {"model": "claude-opus-5-5", "max_tokens": 32,
            "messages": [{"role": "user", "content": "Reply with the single word OK."}]}
    req = urllib.request.Request(f"{proxy.base_url}/c/{cell}/v1/messages", data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json", "anthropic-version": "2023-06-01",
                                          "x-api-key": "proxy"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r: status, resp = r.status, r.read().decode()
    except urllib.error.HTTPError as e: status, resp = e.code, e.read().decode()
    finally: proxy.close()
    rows = [json.loads(l) for p in led.glob("*.jsonl") for l in open(p) if l.strip()]
    rec = {"effort": effort, "cell": cell, "status": status, "response_body": resp, "ledger_rows": rows,
           "effort_env_resolved": None}
    try:
        os.environ["OBENCH_MATCHED_EFFORT"] = effort; rec["effort_env_resolved"] = vap.matched_opus_effort()
    except Exception as e: rec["effort_env_resolved"] = repr(e)
    results.append(rec); (OUT / f"probe-{effort}.json").write_text(json.dumps(rec, indent=2) + "\n")
    print(effort, status, resp[:400], flush=True)
    if status == 200: break
(OUT / "probe-summary.json").write_text(json.dumps([{k: r[k] for k in ("effort", "status", "effort_env_resolved")} for r in results], indent=2) + "\n")
