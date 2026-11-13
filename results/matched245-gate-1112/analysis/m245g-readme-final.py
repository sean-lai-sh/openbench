#!/usr/bin/env python3
"""Tables for the README from analysis/analysis.json + analysis/opencode-proof.json (both computed on the VM from raw files)."""
import json, sys, statistics
A = json.load(open(sys.argv[1])); P = json.load(open(sys.argv[2]))
by = {c["cell"]: c for c in A}
short = lambda n: n.split("-regex")[0]
out = []
def fmt(x): return "–" if x is None else str(x)
# gate table
out.append("| cell | stop | record | requests: proxy / trace / untraced | captures | routed (requested→upstream) | wrong-model rows | received thinking / output_config | upstream thinking / output_config | load_proof | limit.context | outcome | spend |")
out.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for c in A:
    pr = P["cells"].get(c["cell"])
    lp = f'{pr["verdict"]["load_proof"]} ({pr["verdict"]["load_proof_basis"]}: UA {pr["ua_anthropic_version"]} vs pin {P["pin"]}, pin_source={P["pin_source"]})' if pr else "n/a (Pi)"
    ctx = (f'{pr["config_limits"]["anthropic"]["context"]} (config)' if pr else (f'{c["model_context_window"]} (live)' if c["model_context_window"] else ("not in record (stopped by guard)" if c["cell_id"] else "no record")))
    rec = "yes" if c["cell_id"] else "no (SIGTERM)"
    out.append(f'| {short(c["cell"])} | {"cell spend>=$0.55" if c.get("stop")=="cell" else c.get("stop","")} | {rec} | {fmt(c["proxy_requests"])} / {fmt(c["trace_requests"])} / {fmt(c["untraced_requests"])} | {c["captures"]} | {",".join(c["requested_models"])}→{",".join(c["upstream_models"])} | {c["wrong_model_rows"]} | '
               f'{",".join(c["set_received_thinking_json"])} / {",".join(c["set_received_output_config_json"])} | {",".join(c["set_upstream_thinking_json"])} / {",".join(c["set_upstream_output_config_json"])} | {lp} | {ctx} | {fmt(c["failure_class"])} | ${c["cost_usd"]:.3f} |')
out.append("\n### Per-call thinking tokens, cache read / cache write (response usage)\n")
for m in ("claude-sonnet-5-5", "claude-opus-5-5"):
    out.append(f"\n**{m}**\n")
    cs = [c for c in A if c["model"] == m]
    n = max(len(c["calls"]) for c in cs)
    out.append("| call | " + " | ".join(short(c["cell"]) for c in cs) + " |"); out.append("|---|" + "---|" * len(cs))
    for i in range(n):
        row = []
        for c in cs:
            x = c["calls"][i] if i < len(c["calls"]) else None
            row.append(f'{x["thinking_tokens"]} ({x["cache_read"]}/{x["cache_write"]})' if x else "")
        out.append(f"| {i+1} | " + " | ".join(row) + " |")
    out.append("\n| harness | cells | calls | thinking total | mean / call | median / call | calls with thinking > 0 | max |"); out.append("|---|---|---|---|---|---|---|---|")
    for c in cs:
        t = [x["thinking_tokens"] or 0 for x in c["calls"]]
        out.append(f'| {c["harness"]} ({short(c["cell"])}) | 1 | {len(t)} | {sum(t)} | {statistics.mean(t):.1f} | {statistics.median(t):.0f} | {sum(1 for v in t if v)} | {max(t)} |')
    for h in ("pi", "opencode"):
        t = [x["thinking_tokens"] or 0 for c in cs if c["harness"] == h for x in c["calls"]]
        if t: out.append(f'| **{h}, pooled** | {sum(1 for c in cs if c["harness"]==h)} | {len(t)} | {sum(t)} | {statistics.mean(t):.1f} | {statistics.median(t):.0f} | {sum(1 for v in t if v)} | {max(t)} |')
out.append("\n### Upstream thinking / output_config bytes (from the raw upstream bodies)\n")
out.append("| model | Pi upstream bytes | OpenCode upstream bytes | identical |"); out.append("|---|---|---|---|")
for m in ("claude-sonnet-5-5", "claude-opus-5-5"):
    s = {h: sorted({(o["upstream_thinking_bytes"], o["upstream_output_config_bytes"]) for c in A if c["model"] == m and c["harness"] == h for o in c["main_offsets"]}) for h in ("pi", "opencode")}
    f = lambda v: "; ".join(f'`"thinking": {a}`' + (f', `"output_config": {b}`' if b else ", no output_config") for a, b in v)
    out.append(f'| {m} | {f(s["pi"])} | {f(s["opencode"])} | {"YES" if s["pi"] == s["opencode"] and len(s["pi"]) == 1 else "NO"} |')
out.append("\n### Raw-byte offsets (consecutive main calls)\n")
out.append("| cell | pairs | first div at prev cc marker (received / upstream) | append-only with cc stripped (received / upstream) | exceptions |"); out.append("|---|---|---|---|---|")
for c in A:
    o = [x for x in c["main_offsets"] if "upstream_first_div" in x]
    ex = [f'main {x["main_call"]}: rcv div {x.get("received_first_div")} {x.get("received_append_only_nocc")}' for x in o if not (x.get("received_div_at_cc_marker") and x.get("upstream_div_at_cc_marker") and x.get("received_append_only_nocc") == "Y" and x.get("upstream_append_only_nocc") == "Y")]
    out.append(f'| {short(c["cell"])} | {len(o)} | {sum(1 for x in o if x.get("received_div_at_cc_marker"))} / {sum(1 for x in o if x.get("upstream_div_at_cc_marker"))} | {sum(1 for x in o if x.get("received_append_only_nocc")=="Y")} / {sum(1 for x in o if x.get("upstream_append_only_nocc")=="Y")} | {"; ".join(ex) or "none"} |')
print("\n".join(out))
