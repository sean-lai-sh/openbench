#!/usr/bin/env python3
"""#245 gate smoke at 77644112: per-cell proof fields, per-call table, raw-byte offsets, cross-harness upstream bytes.
All byte work is on the RAW captured files (requests/NNNN.{received.bin,upstream.json}) on the VM."""
import json, glob, os, sys, hashlib, re, statistics
REPO = os.path.expanduser("~/ob-m245g"); sys.path.insert(0, REPO)
from thesis.ab.summarize import row_cost
import thesis.ab.vertex_anthropic_proxy as v
B = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else "~/h2/matched245-gate-1112")
CCS = [b',"cache_control":{"type":"ephemeral"}', b', "cache_control": {"type": "ephemeral"}']
def cp(a, b):
    n = min(len(a), len(b)); i = 0
    while i < n and a[i] == b[i]: i += 1
    return i
def nocc(o):
    if isinstance(o, dict): return {k: nocc(x) for k, x in o.items() if k != "cache_control"}
    if isinstance(o, list): return [nocc(x) for x in o]
    return o
def append_only(p, c):
    p, c = nocc(p), nocc(c)
    if any(p.get(k) != c.get(k) for k in set(p) | set(c) if k != "messages"): return "other keys: " + ",".join(sorted(k for k in set(p) | set(c) if k != "messages" and p.get(k) != c.get(k)))
    pm, cm = p.get("messages") or [], c.get("messages") or []
    return "Y" if cm[:len(pm)] == pm else "N"
def val_bytes(raw, d, key):
    if key not in d: return None
    for sep in (b'"%s": ' % key.encode(), b'"%s":' % key.encode()):
        frag = json.dumps(d[key], separators=(", ", ": ") if b": " in sep else (",", ":")).encode()
        if raw.find(sep + frag) >= 0: return frag
    return b"?not-found"
cells = []
for d in sorted(glob.glob(f"{B}/cells/*")):
    name = os.path.basename(d); h = name.split("-")[1]; m = "claude-opus-5-5" if "opus" in name else "claude-sonnet-5-5"
    recs = glob.glob(f"{d}/{h}/claude-*.json"); rec = json.load(open(recs[0])) if recs else {}; row = rec.get("row") or {}
    led = [f for f in glob.glob(f"{d}/{h}/proxy-ledger/*.jsonl") if os.path.basename(f)[:-6].isalnum()]
    rows = [json.loads(l) for f in led for l in open(f) if l.strip()]
    rq = f"{d}/{h}/requests"; caps = []
    for mf in sorted(glob.glob(f"{rq}/*.meta.json")):
        k = int(os.path.basename(mf)[:4]); meta = json.load(open(mf))
        up = open(f"{rq}/{k:04d}.upstream.json", "rb").read(); ud = json.loads(up)
        rf = f"{rq}/{k:04d}.received.bin"; rv = open(rf, "rb").read() if os.path.exists(rf) else None; rd = json.loads(rv) if rv else None
        role = v.classify_call_role(rd if isinstance(rd, dict) else ud, None)
        role = role.get("call_role") if isinstance(role, dict) else role
        if not ud.get("tools"): role = "title"  # OpenCode title call: no tools, short system; excluded from main-call offsets
        caps.append({"k": k, "t": meta.get("t_forward"), "role": role, "up": up, "ud": ud, "rv": rv, "rd": rd, "route": meta.get("translate_route")})
    mains = [c for c in sorted(caps, key=lambda c: c["t"] or 0) if c["role"] == "main"]
    main_rows = [r for r in rows if r.get("call_role") == "main"]
    calls = []; prev = None
    for i, r in enumerate(rows):
        calls.append({"n": i + 1, "role": r.get("call_role"), "status": r.get("status"), "requested": r.get("requested_model"), "upstream": r.get("upstream_model"),
                      "cache_read": r.get("cache_read"), "cache_write": r.get("cache_write"), "input_uncached": r.get("input_uncached"), "output": r.get("output"),
                      "thinking_tokens": r.get("thinking_tokens"), "usage_thinking": ((r.get("usage") or {}).get("output_tokens_details") or {}).get("thinking_tokens"),
                      "received_thinking_json": r.get("received_thinking_json"), "received_output_config_json": r.get("received_output_config_json"),
                      "upstream_thinking_json": r.get("upstream_thinking_json"), "upstream_output_config_json": r.get("upstream_output_config_json")})
    offs = []
    for j, c in enumerate(mains):
        o = {"main_call": j + 1, "capture": c["k"], "upstream_sha256": hashlib.sha256(c["up"]).hexdigest(),
             "received_sha256": hashlib.sha256(c["rv"]).hexdigest() if c["rv"] else None,
             "upstream_thinking_bytes": (val_bytes(c["up"], c["ud"], "thinking") or b"").decode(), "upstream_output_config_bytes": (val_bytes(c["up"], c["ud"], "output_config") or b"").decode(),
             "received_thinking": c["rd"].get("thinking") if isinstance(c["rd"], dict) else None, "received_output_config": c["rd"].get("output_config") if isinstance(c["rd"], dict) else None}
        if prev:
            for kind, a, b, pa, pb in (("received", prev["rv"], c["rv"], prev["rd"], c["rd"]), ("upstream", prev["up"], c["up"], prev["ud"], c["ud"])):
                if a is None or b is None: continue
                x = cp(a, b); ccpos = sorted({i for s in CCS for i in [m_.start() for m_ in re.finditer(re.escape(s), a)]})
                o[f"{kind}_first_div"] = x; o[f"{kind}_div_at_cc_marker"] = x in ccpos
                o[f"{kind}_append_only_nocc"] = append_only(pa, pb)
        offs.append(o); prev = c
    th = [c["thinking_tokens"] for c in calls if c["thinking_tokens"] is not None]
    keys = {k: row.get(k) for k in sorted(row) if re.search(r"load_proof|pin|provider|context|limit|sdk|loaded", k)}
    cells.append({"cell": name, "harness": h, "model": m, "cell_id": rec.get("cell_id"),
        "proxy_requests": rec.get("proxy_requests"), "trace_requests": rec.get("trace_requests"), "untraced_requests": rec.get("untraced_requests"),
        "ledger_rows": len(rows), "captures": len(caps), "capture_roles": [c["role"] for c in sorted(caps, key=lambda c: c["t"] or 0)],
        "statuses": sorted({str(r.get("status")) for r in rows}), "requested_models": sorted({str(r.get("requested_model")) for r in rows}),
        "upstream_models": sorted({str(r.get("upstream_model")) for r in rows}), "wrong_model_rows": sum(1 for r in rows if r.get("upstream_model") != m or (r.get("requested_model") and m not in str(r.get("requested_model")))),
        "set_received_thinking_json": sorted({str(r.get("received_thinking_json")) for r in rows}), "set_received_output_config_json": sorted({str(r.get("received_output_config_json")) for r in rows}),
        "set_upstream_thinking_json": sorted({str(r.get("upstream_thinking_json")) for r in rows}), "set_upstream_output_config_json": sorted({str(r.get("upstream_output_config_json")) for r in rows}),
        "set_upstream_thinking_bytes": sorted({o["upstream_thinking_bytes"] for o in offs}), "set_upstream_output_config_bytes": sorted({o["upstream_output_config_bytes"] for o in offs}),
        "thinking_tokens_total": sum(th), "thinking_tokens_mean": round(statistics.mean(th), 1) if th else None, "thinking_nonzero_calls": sum(1 for t in th if t),
        "cost_usd": round(sum(row_cost({"upstream_model": r.get("upstream_model") or m, "tokens_input_uncached": r.get("input_uncached") or 0, "tokens_output": r.get("output") or 0,
                       "tokens_cache_read": r.get("cache_read") or 0, "tokens_cache_write": r.get("cache_write") or 0}) or 0 for r in rows), 4),
        "completed": row.get("completed"), "failure_class": row.get("failure_class"), "checker_exit": row.get("checker_exit"),
        "model_context_window": row.get("model_context_window"), "proof_keys": keys, "settings": rec.get("settings"), "calls": calls, "main_offsets": offs})
ends = {}
for l in open(f"{B}/batch.log"):
    mm = re.search(r" end (\d+) .* stopped=(\S+)", l)
    if mm: ends[mm.group(1)] = mm.group(2)
for c in cells:
    c["stop"] = ends.get(c["cell"].split("-")[0], "?")
    betas = set()
    for f in glob.glob(f"{B}/cells/{c['cell']}/*/proxy-ledger/*.cache-miss-headers.jsonl"):
        for l in open(f):
            r = json.loads(l); betas.add(((r.get("upstream_headers") or {}).get("anthropic-beta"), next((v for k, v in (r.get("request_headers") or {}).items() if k.lower() == "anthropic-beta"), None)))
    c["anthropic_beta_upstream_received"] = sorted(map(list, betas))
json.dump(cells, open(f"{B}/analysis.json", "w"), indent=1)
for c in cells:
    print("##", c["cell"], {k: c[k] for k in ("proxy_requests", "trace_requests", "untraced_requests", "ledger_rows", "captures", "statuses", "requested_models", "upstream_models", "wrong_model_rows",
          "set_received_thinking_json", "set_received_output_config_json", "set_upstream_thinking_json", "set_upstream_output_config_json", "set_upstream_thinking_bytes",
          "set_upstream_output_config_bytes", "thinking_tokens_total", "thinking_tokens_mean", "thinking_nonzero_calls", "cost_usd", "completed", "failure_class", "checker_exit", "model_context_window")})
    print("   proof", json.dumps(c["proof_keys"])[:1500]); print("   roles", c["capture_roles"])
    for x in c["calls"]: print("   call", x["n"], x["role"], x["status"], "cr", x["cache_read"], "cw", x["cache_write"], "th", x["thinking_tokens"], x["usage_thinking"], "out", x["output"])
    for o in c["main_offsets"]: print("   main", o["main_call"], "cap", o["capture"], {k: o.get(k) for k in ("received_first_div", "received_div_at_cc_marker", "received_append_only_nocc", "upstream_first_div", "upstream_div_at_cc_marker", "upstream_append_only_nocc")})
