#!/usr/bin/env python3
"""Per-call prefix divergence on RAW captured bodies (client = before proxy edit, forwarded = after)."""
import json, glob, os, sys, hashlib
B = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else "~/h2/matched245-cachediv-1112")
def common_prefix(a, b):
    n = min(len(a), len(b)); i = 0
    while i < n and a[i] == b[i]: i += 1
    return i
def bps(d, raw):
    out = []
    def walk(o, path):
        if isinstance(o, dict):
            if "cache_control" in o:
                frag = json.dumps(o).encode(); off = raw.find(frag)
                out.append({"path": path, "start": off, "end": off + len(frag) if off >= 0 else None})
            for k, v in o.items(): walk(v, f"{path}.{k}")
        elif isinstance(o, list):
            for i, v in enumerate(o): walk(v, f"{path}[{i}]")
    for sec in ("tools", "system", "messages"): walk(d.get(sec), sec)
    return out
def block_sig(b):
    if not isinstance(b, dict): return repr(type(b))
    t = b.get("type"); s = t
    if t == "thinking": s += f"(len={len(b.get('thinking',''))},sig={'Y' if b.get('signature') else 'N'})"
    if t == "redacted_thinking": s += "(redacted)"
    if "cache_control" in b: s += "+cc"
    return s
def nocc(o):
    if isinstance(o, dict): return {k: nocc(v) for k, v in o.items() if k != "cache_control"}
    if isinstance(o, list): return [nocc(v) for v in o]
    return o
def struct_diff(p, c):
    """First structural difference of the prompt prefix in cache order: tools, system, messages."""
    for sec in ("tools", "system"):
        if p.get(sec) != c.get(sec): 
            pl, cl = p.get(sec) or [], c.get(sec) or []
            for i in range(max(len(pl), len(cl))):
                a = pl[i] if i < len(pl) else None; b = cl[i] if i < len(cl) else None
                if a != b:
                    keys = sorted(set((a or {}).keys()) | set((b or {}).keys())) if isinstance(a, dict) or isinstance(b, dict) else []
                    return {"where": f"{sec}[{i}]", "keys_differ": [k for k in keys if (a or {}).get(k) != (b or {}).get(k)]}
    for k in ("thinking", "output_config", "model", "max_tokens"):
        if p.get(k) != c.get(k): top = {"top_level_changed": k, "prev": p.get(k), "cur": c.get(k)}; break
    else: top = None
    pm, cm = p.get("messages") or [], c.get("messages") or []
    for i, a in enumerate(pm):
        if i >= len(cm): return {"where": f"messages[{i}]", "what": "message removed", "top": top}
        b = cm[i]
        if a == b: continue
        if a.get("role") != b.get("role"): return {"where": f"messages[{i}].role", "top": top}
        ac, bc = a.get("content"), b.get("content")
        if isinstance(ac, str) or isinstance(bc, str):
            return {"where": f"messages[{i}].content", "what": "string content changed", "prev": str(ac)[:80], "cur": str(bc)[:80], "top": top}
        for j in range(max(len(ac), len(bc))):
            x = ac[j] if j < len(ac) else None; y = bc[j] if j < len(bc) else None
            if x != y:
                diffk = sorted(k for k in set((x or {}).keys()) | set((y or {}).keys()) if (x or {}).get(k) != (y or {}).get(k))
                return {"where": f"messages[{i}].content[{j}]", "role": a.get("role"), "prev_block": block_sig(x) if x else None,
                        "cur_block": block_sig(y) if y else None, "keys_differ": diffk,
                        "prev_blocks": [block_sig(z) for z in ac], "cur_blocks": [block_sig(z) for z in bc], "top": top}
    return {"where": "append-only" if len(cm) >= len(pm) else "?", "top": top}
res = {}
for cell in sorted(glob.glob(f"{B}/cells/*")):
    name = os.path.basename(cell); rq = f"{cell}/pi/requests"
    led = [f for f in glob.glob(f"{cell}/pi/proxy-ledger/*.jsonl") if "cache-miss" not in f]
    rows = [json.loads(l) for f in led for l in open(f) if l.strip()]
    n = len(glob.glob(f"{rq}/*.client.json")); calls = []; prev = {}
    for k in range(1, n + 1):
        rec = {"call": k}
        for kind in ("client", "forwarded"):
            raw = open(f"{rq}/{k:04d}.{kind}.json", "rb").read(); d = json.loads(raw)
            rec[f"{kind}_sha256"] = hashlib.sha256(raw).hexdigest(); rec[f"{kind}_bytes"] = len(raw)
            if kind in prev:
                praw, pd = prev[kind]
                off = common_prefix(praw, raw)
                mpos = praw.find(b'"messages": ')
                pm_end = mpos + len(b'"messages": ') + len(json.dumps(pd["messages"]).encode()) if mpos >= 0 else None
                rec[f"{kind}_first_div_byte"] = off
                rec[f"{kind}_prev_messages_end_byte"] = pm_end
                rec[f"{kind}_div_inside_old_history"] = (pm_end is not None and off < pm_end - 1)
                rec[f"{kind}_struct_raw"] = struct_diff(pd, d)
                rec[f"{kind}_struct"] = struct_diff(nocc(pd), nocc(d))
            if kind == "forwarded":
                rec["breakpoints"] = bps(d, raw); rec["thinking_field"] = d.get("thinking"); rec["output_config"] = d.get("output_config")
                rec["n_messages"] = len(d.get("messages") or [])
                rec["assistant_blocks"] = [[block_sig(z) for z in m["content"]] for m in d["messages"] if m.get("role") == "assistant" and isinstance(m.get("content"), list)]
            prev[kind] = (raw, d)
        meta = json.load(open(f"{rq}/{k:04d}.meta.json")); rec["proxy_edit_changed"] = meta["changed"]
        if k - 1 < len(rows):
            r = rows[k - 1]
            rec.update({"status": r.get("status"), "cache_read": r.get("cache_read"), "cache_write": r.get("cache_write"),
                        "thinking_tokens": r.get("thinking_tokens"), "output": r.get("output"), "thinking_json": r.get("thinking_json"),
                        "output_config_json": r.get("output_config_json"), "error": (r.get("error") or "")[:300] or None})
        calls.append(rec)
    res[name] = calls
json.dump(res, open(f"{B}/divergence.json", "w"), indent=1)
for name, calls in res.items():
    print("##", name)
    for c in calls:
        print(c["call"], c.get("status"), "cr", c.get("cache_read"), "cw", c.get("cache_write"), "th", c.get("thinking_tokens"), "edit", c["proxy_edit_changed"],
              "cdiv", c.get("client_first_div_byte"), "/", c.get("client_prev_messages_end_byte"), c.get("client_div_inside_old_history"),
              "fdiv", c.get("forwarded_first_div_byte"), c.get("forwarded_div_inside_old_history"),
              "| struct(no cc)", json.dumps(c.get("client_struct"))[:500], "| fwd", json.dumps(c.get("forwarded_struct"))[:200])
        print("    asst", c["assistant_blocks"], "bp", [(b["path"], b["start"]) for b in c["breakpoints"]], "think", c["thinking_field"], c["output_config"])
