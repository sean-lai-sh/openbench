#!/usr/bin/env python3
"""Per-call tables for the #245 cache-divergence run (A matched, B passthrough). Reads RAW captured bodies.
For each call k>=2 and each of client (Pi's bytes, before the proxy edit) and forwarded (after the edit):
  raw_div   = first byte where body k differs from body k-1 (raw bytes as captured)
  cc_at     = byte offset in body k-1 of the cache_control marker on its last message block (Pi moves this marker each call)
  nocc_div  = first differing byte after removing every cache_control key from both bodies (same json.dumps)
  nocc_end  = byte offset in nocc(body k-1) where its messages array closes; nocc_div == nocc_end means body k
              only appends to the prior history (nothing earlier changed)
Also client->forwarded: which top-level keys the proxy edit changed and the first byte it changed."""
import json, glob, os, sys, hashlib, time
B = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else "~/h2/matched245-cachediv-1112")
def cp(a, b):
    n = min(len(a), len(b)); i = 0
    while i < n and a[i] == b[i]: i += 1
    return i
def nocc(o):
    if isinstance(o, dict): return {k: nocc(v) for k, v in o.items() if k != "cache_control"}
    if isinstance(o, list): return [nocc(v) for v in o]
    return o
CC = b', "cache_control": {"type": "ephemeral"}'
out = {}; md = []
for cell in sorted(glob.glob(f"{B}/cells/*")):
    name = os.path.basename(cell); rq = f"{cell}/pi/requests"
    led = [f for f in glob.glob(f"{cell}/pi/proxy-ledger/*.jsonl") if "cache-miss" not in f]
    rows = [json.loads(l) for f in led for l in open(f) if l.strip()]
    n = len(glob.glob(f"{rq}/*.client.json")); prev = None; calls = []
    for k in range(1, n + 1):
        c_raw = open(f"{rq}/{k:04d}.client.json", "rb").read(); f_raw = open(f"{rq}/{k:04d}.forwarded.json", "rb").read()
        c, f = json.loads(c_raw), json.loads(f_raw)
        t = os.path.getmtime(f"{rq}/{k:04d}.client.json")
        r = rows[k - 1] if k - 1 < len(rows) else {}
        rec = {"call": k, "start_utc": time.strftime("%H:%M:%S", time.gmtime(t)), "gap_s": round(t - prev["t"], 1) if prev else None,
               "status": r.get("status"), "input_uncached": r.get("input_uncached"), "cache_read": r.get("cache_read"), "cache_write": r.get("cache_write"),
               "output": r.get("output"), "thinking_tokens": r.get("thinking_tokens"),
               "client_sha256": hashlib.sha256(c_raw).hexdigest(), "forwarded_sha256": hashlib.sha256(f_raw).hexdigest(),
               "client_bytes": len(c_raw), "forwarded_bytes": len(f_raw),
               "client_thinking": c.get("thinking"), "client_output_config": c.get("output_config"),
               "fwd_thinking": f.get("thinking"), "fwd_output_config": f.get("output_config"),
               "edit_keys": sorted(x for x in set(c) | set(f) if c.get(x) != f.get(x)),
               "edit_first_byte": cp(c_raw, f_raw) if c_raw != f_raw else None,
               "edit_nonthinking_change": nocc({x: v for x, v in c.items() if x not in ("thinking", "output_config")}) != nocc({x: v for x, v in f.items() if x not in ("thinking", "output_config")})}
        for kind, raw, d in (("client", c_raw, c), ("fwd", f_raw, f)):
            if prev:
                praw, pd = prev[kind]
                rec[f"{kind}_raw_div"] = cp(praw, raw)
                me = praw.rfind(b'}]}], "max_tokens"') if praw.rfind(b'}]}], "max_tokens"') >= 0 else None
                ccs = [i for i in range(len(praw)) if praw.startswith(CC, i)] if False else None
                # cc marker on the last message block of the previous body (Pi puts it on the final user block)
                pm = json.dumps(pd["messages"]).encode(); mpos = praw.find(b'"messages": ') + len(b'"messages": ')
                rec[f"{kind}_prev_cc_at"] = mpos + pm.rfind(CC)
                a = json.dumps(nocc(pd)).encode(); b = json.dumps(nocc(d)).encode()
                rec[f"{kind}_nocc_div"] = cp(a, b)
                pmn = json.dumps(nocc(pd["messages"])).encode(); mposn = a.find(b'"messages": ') + len(b'"messages": ')
                rec[f"{kind}_nocc_prev_msgs_close"] = mposn + len(pmn) - 1
                rec[f"{kind}_append_only"] = rec[f"{kind}_nocc_div"] == rec[f"{kind}_nocc_prev_msgs_close"]
                rec[f"{kind}_raw_div_is_cc_marker"] = rec[f"{kind}_raw_div"] == rec[f"{kind}_prev_cc_at"]
                # same top-level non-message keys?
                rec[f"{kind}_nonmsg_keys_changed"] = sorted(x for x in set(pd) | set(d) if x != "messages" and nocc(pd.get(x)) != nocc(d.get(x)))
        calls.append(rec); prev = {"t": t, "client": (c_raw, c), "fwd": (f_raw, f)}
    out[name] = calls
    md.append(f"\n### {name}\n")
    md.append("| call | start UTC | gap s | status | cache read | cache write | uncached in | output | thinking tok | Pi-byte div (prev cc marker) | fwd-byte div | append-only (cc stripped) client/fwd | other keys changed |")
    md.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for x in calls:
        md.append(f"| {x['call']} | {x['start_utc']} | {x['gap_s'] if x['gap_s'] is not None else '–'} | {x['status'] or 'killed in flight'} | {x['cache_read'] if x['cache_read'] is not None else '–'} | {x['cache_write'] if x['cache_write'] is not None else '–'} | {x['input_uncached'] if x['input_uncached'] is not None else '–'} | {x['output'] if x['output'] is not None else '–'} | {x['thinking_tokens'] if x['thinking_tokens'] is not None else '–'} | "
                  + (f"{x['client_raw_div']} ({x['client_prev_cc_at']})" if x['call'] > 1 else "–") + " | "
                  + (f"{x['fwd_raw_div']}" if x['call'] > 1 else "–") + " | "
                  + (f"{'Y' if x['client_append_only'] else 'N'}/{'Y' if x['fwd_append_only'] else 'N'}" if x['call'] > 1 else "–") + " | "
                  + (", ".join(x['client_nonmsg_keys_changed']) or "none" if x['call'] > 1 else "–") + " |")
json.dump(out, open(f"{B}/per-call.json", "w"), indent=1)
open(f"{B}/per-call.md", "w").write("\n".join(md) + "\n")
print("\n".join(md))
for name, calls in out.items():
    print(name, "edit keys", {json.dumps(x['edit_keys']) for x in calls}, "edit first byte", {x['edit_first_byte'] for x in calls},
          "nonthinking change", {x['edit_nonthinking_change'] for x in calls}, "raw div == cc marker (client/fwd)",
          {(x.get('client_raw_div_is_cc_marker'), x.get('fwd_raw_div_is_cc_marker')) for x in calls[1:]},
          "client==fwd div", all(x.get('client_raw_div') == x.get('fwd_raw_div') for x in calls[1:]))
