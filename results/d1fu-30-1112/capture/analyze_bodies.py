#!/usr/bin/env python3
"""D1 prompt follow-up 30/side: per-call cache-prefix offsets on RAW captured bodies,
cell<->ledger mapping, cache read split (call 1 cross-cell vs call 2+ within-cell),
timeline, and per-arm cache cost. Reads only; writes JSON/CSV/MD to --out.
Usage: analyze_bodies.py <run_dir> --out <dir>"""
import csv, glob, hashlib, json, os, sys
from datetime import datetime, timedelta

R = sys.argv[1]; OUT = sys.argv[sys.argv.index("--out") + 1]; os.makedirs(OUT, exist_ok=True)
PRICES = json.load(open(sys.argv[sys.argv.index("--prices") + 1]))["models"]["claude-sonnet-5-5"]
TTL = 300

def canon(x): return json.dumps(x, sort_keys=True, separators=(",", ":"))
def strip_cc(x):
    if isinstance(x, dict): return {k: strip_cc(v) for k, v in x.items() if k != "cache_control"}
    if isinstance(x, list): return [strip_cc(v) for v in x]
    return x
def h(s): return hashlib.sha256(s.encode() if isinstance(s, str) else s).hexdigest()[:16]
def lcp(a, b):
    n = min(len(a), len(b)); i = 0
    # chunked compare
    step = 4096
    while i + step <= n and a[i:i+step] == b[i:i+step]: i += step
    while i < n and a[i] == b[i]: i += 1
    return i
def blocks(body):
    """Anthropic cache order: tools -> system -> messages (content blocks)."""
    out = []
    for i, t in enumerate(body.get("tools") or []): out.append((f"tools[{i}]", canon(strip_cc(t))))
    sysv = body.get("system")
    if isinstance(sysv, str): out.append(("system", canon(sysv)))
    else:
        for i, s in enumerate(sysv or []): out.append((f"system[{i}]", canon(strip_cc(s))))
    for mi, m in enumerate(body.get("messages") or []):
        c = m.get("content")
        if isinstance(c, str): out.append((f"messages[{mi}]({m['role']})", canon([m["role"], c])))
        else:
            for ci, b in enumerate(c or []): out.append((f"messages[{mi}].content[{ci}]({m['role']})", canon([m["role"], strip_cc(b)])))
    return out
def cc_positions(body):
    pos = []
    for i, t in enumerate(body.get("tools") or []):
        if t.get("cache_control"): pos.append(f"tools[{i}]")
    for i, s in enumerate(body.get("system") or [] if isinstance(body.get("system"), list) else []):
        if s.get("cache_control"): pos.append(f"system[{i}]")
    for mi, m in enumerate(body.get("messages") or []):
        if isinstance(m.get("content"), list):
            for ci, b in enumerate(m["content"]):
                if isinstance(b, dict) and b.get("cache_control"): pos.append(f"messages[{mi}].content[{ci}]")
    return pos

# rows
rows = []
for arm in ("without", "with"):
    for l in open(f"{R}/725226/{arm}.jsonl"):
        r = json.loads(l); r["_arm"] = arm; rows.append(r)
# ledgers
led = {}
for f in glob.glob(f"{R}/proxy-ledger/*.jsonl"):
    if f.endswith(".cache-miss-headers.jsonl"): continue
    cid = os.path.basename(f)[:-6]
    led[cid] = [json.loads(l) for l in open(f) if l.strip()]
def key_from_led(calls):
    return (sum(c.get("cache_read") or 0 for c in calls), sum(c.get("cache_write") or 0 for c in calls),
            sum(c.get("input_uncached") or 0 for c in calls), sum(c.get("output") or 0 for c in calls), len(calls))
def key_from_row(r):
    return (r.get("tokens_proxy_cache_read"), r.get("tokens_proxy_cache_write"), r.get("tokens_proxy_input_uncached"),
            r.get("tokens_proxy_output"), r.get("tokens_proxy_calls"))
bykey = {}
for cid, calls in led.items(): bykey.setdefault(key_from_led(calls), []).append(cid)
# bodies
def load_cell(cid):
    d = f"{R}/request-bodies/{cid}"
    metas = [json.loads(l) for l in open(f"{d}/meta.jsonl")] if os.path.exists(f"{d}/meta.jsonl") else []
    out = []
    for m in sorted(metas, key=lambda x: x["i"]):
        raw = open(f"{d}/{m['i']:04d}.forwarded.bin", "rb").read()
        assert hashlib.sha256(raw).hexdigest() == m["forwarded_sha256"]
        out.append((m, raw, json.loads(raw)))
    return out
# arm fingerprint from bash tool description in call 1
bash_desc_arm = {}
mapping = {}; problems = []
for r in rows:
    k = key_from_row(r); c = bykey.get(k, [])
    if len(c) != 1: problems.append(f"{r['_arm']} trial {r['trial']}: {len(c)} ledger matches for {k}"); continue
    mapping[(r["_arm"], r["trial"])] = c[0]
cells = []
for r in rows:
    cid = mapping.get((r["_arm"], r["trial"]))
    if not cid: continue
    calls = load_cell(cid)
    if len(calls) != len(led[cid]): problems.append(f"{cid}: bodies {len(calls)} != ledger {len(led[cid])}")
    b1 = calls[0][2]
    bash = next((t for t in b1.get("tools", []) if t.get("name") == "bash"), {})
    tools_sys = canon([strip_cc(b1.get("tools")), strip_cc(b1.get("system"))])
    cells.append({"arm": r["_arm"], "trial": r["trial"], "cell": cid, "row": r, "calls": calls, "ledger": led[cid],
                  "bash_desc_sha": h(bash.get("description", "")), "tools_sys_sha": h(tools_sys),
                  "tools_sha": h(canon(strip_cc(b1.get("tools")))), "system_sha": h(canon(strip_cc(b1.get("system"))))})
for c in cells: bash_desc_arm.setdefault(c["arm"], set()).add(c["bash_desc_sha"])

def ts(m): return datetime.strptime(m["ts"], "%Y-%m-%dT%H:%M:%S%z")
percall = []
all_calls = []  # (ts, arm, trial, i, tools_sys_sha)
for c in cells:
    prev = None
    for idx, (m, raw, body) in enumerate(c["calls"]):
        L = c["ledger"][idx] if idx < len(c["ledger"]) else {}
        bl = blocks(body)
        tsys = canon([strip_cc(body.get("tools")), strip_cc(body.get("system"))])
        rec = {"arm": c["arm"], "trial": c["trial"], "cell": c["cell"], "i": m["i"], "ts": m["ts"],
               "forwarded_sha256": m["forwarded_sha256"], "forwarded_bytes": m["forwarded_bytes"],
               "client_bytes_equal_pre_translate": m.get("client_bytes_equal_pre_translate"),
               "n_blocks": len(bl), "tools_system_sha": h(tsys), "cache_control_at": cc_positions(body),
               "cache_read": L.get("cache_read"), "cache_write": L.get("cache_write"),
               "input_uncached": L.get("input_uncached"), "output": L.get("output")}
        if prev is not None:
            pm, praw, pbody, pbl = prev
            rec["raw_lcp_bytes_vs_prev"] = lcp(raw, praw)
            rec["raw_prev_bytes"] = len(praw)
            j = 0
            while j < min(len(bl), len(pbl)) and bl[j] == pbl[j]: j += 1
            rec["first_divergent_block_vs_prev"] = None if j == len(pbl) and len(bl) >= len(pbl) else (bl[j][0] if j < len(bl) else "(shorter)")
            rec["prev_blocks_are_prefix"] = j == len(pbl)
            rec["common_blocks_vs_prev"] = j
            rec["tools_system_same_as_prev"] = rec["tools_system_sha"] == prev_tsys
        percall.append(rec); all_calls.append((ts(m), c["arm"], c["trial"], m["i"], rec["tools_system_sha"], c["cell"]))
        prev = (m, raw, body, bl); prev_tsys = rec["tools_system_sha"]
all_calls.sort()
# cross-cell writers for call-1 reads
cellinfo = []
for c in cells:
    r = c["row"]; m1 = c["calls"][0][0]; t1 = ts(m1); L1 = c["ledger"][0]
    writers = [(t, a, tr, i) for (t, a, tr, i, s, cid) in all_calls
               if cid != c["cell"] and s == c["tools_sys_sha"] and timedelta(0) < t1 - t <= timedelta(seconds=TTL)]
    st = datetime.fromisoformat(r["started_et"]); en = datetime.fromisoformat(r["ended_et"])
    conc = [f"{o['arm']}#{o['trial']}" for o in cells if o is not c and
            datetime.fromisoformat(o["row"]["started_et"]) < en and datetime.fromisoformat(o["row"]["ended_et"]) > st]
    before = sorted([o for o in cells if datetime.fromisoformat(o["row"]["started_et"]) < st],
                    key=lambda o: o["row"]["started_et"])
    imm = before[-1] if before else None
    total1 = (L1.get("cache_read") or 0) + (L1.get("cache_write") or 0) + (L1.get("input_uncached") or 0)
    b1 = c["calls"][0][2]
    ts_bytes = len(canon([b1.get("tools"), b1.get("system")])); msg_bytes = len(canon(b1.get("messages")))
    cellinfo.append({
        "arm": c["arm"], "trial": c["trial"], "cell": c["cell"], "started_et": r["started_et"], "ended_et": r["ended_et"],
        "schedule_index": r.get("schedule_index"), "solved": r.get("failure_class") == "solved", "failure_class": r.get("failure_class"),
        "success": r.get("success"), "load_proof": r.get("load_proof"), "calls": len(c["calls"]),
        "proxy_cost_usd": r.get("proxy_cost_usd"),
        "immediately_before": f"{imm['arm']}#{imm['trial']}" if imm else None,
        "concurrent_with": conc,
        "call1_cache_read": L1.get("cache_read"), "call1_cache_write": L1.get("cache_write"), "call1_total_input": total1,
        "call1_tools_system_sha": c["tools_sys_sha"], "call1_tools_system_bytes": ts_bytes, "call1_messages_bytes": msg_bytes,
        "call1_unread_tokens": total1 - (L1.get("cache_read") or 0),
        "call1_writer_candidates_same_prefix_within_5m": [f"{a}#{tr}.call{i}@{t.strftime('%H:%M:%S')}" for (t, a, tr, i) in writers][-5:],
        "call1_writer_arms": sorted({a for (_, a, _, _) in writers}),
        "later_cache_read": sum((x.get("cache_read") or 0) for x in c["ledger"][1:]),
        "cache_read_total": sum((x.get("cache_read") or 0) for x in c["ledger"]),
        "cache_write_total": sum((x.get("cache_write") or 0) for x in c["ledger"]),
        "input_uncached_total": sum((x.get("input_uncached") or 0) for x in c["ledger"]),
        "output_total": sum((x.get("output") or 0) for x in c["ledger"]),
    })
cellinfo.sort(key=lambda x: x["started_et"])
# per-arm summaries
def usd(read, write, unc=0, out=0):
    return read / 1e6 * PRICES["cache_read"] + write / 1e6 * PRICES["cache_write"] + unc / 1e6 * PRICES["input"] + out / 1e6 * PRICES["output"]
arms = {}
for arm in ("without", "with"):
    ci = [x for x in cellinfo if x["arm"] == arm]; pc = [x for x in percall if x["arm"] == arm]
    c1r = sum(x["call1_cache_read"] or 0 for x in ci); lr = sum(x["later_cache_read"] for x in ci)
    w = sum(x["cache_write_total"] for x in ci); unc = sum(x["input_uncached_total"] for x in ci); out = sum(x["output_total"] for x in ci)
    later = [x for x in pc if x["i"] >= 2]
    tsys_set = {x["tools_system_sha"] for x in pc}
    a = {
        "cells": len(ci), "solved": sum(x["solved"] for x in ci), "success_true": sum(bool(x["success"]) for x in ci),
        "load_proof_pass": sum(x["load_proof"] == "pass" for x in ci), "calls": len(pc),
        "spend_usd_rows": round(sum(x["proxy_cost_usd"] or 0 for x in ci), 4),
        "cache_read_total": c1r + lr, "cache_read_call1_cross_cell": c1r, "cache_read_call2plus_within_cell": lr,
        "cells_with_call1_read": sum(1 for x in ci if (x["call1_cache_read"] or 0) > 0),
        "calls2plus_with_read": sum(1 for x in later if (x["cache_read"] or 0) > 0), "calls2plus": len(later),
        "cache_write_total": w, "input_uncached_total": unc, "output_total": out,
        "cache_usd_including_cross_cell_reads": round(usd(c1r + lr, w), 4),
        # within-cell view: call-1 cross-cell reads repriced as the writes they would otherwise have been
        "cache_usd_within_cell_only_call1_reads_as_writes": round(usd(lr, w + c1r), 4),
        "total_usd_including_cross_cell_reads": round(usd(c1r + lr, w, unc, out), 4),
        "total_usd_within_cell_only": round(usd(lr, w + c1r, unc, out), 4),
        "distinct_tools_system_prefixes_all_calls": len(tsys_set),
        "distinct_tools_system_prefixes_call1": len({x["tools_system_sha"] for x in pc if x["i"] == 1}),
        "calls2plus_tools_system_same_as_prev": sum(1 for x in later if x.get("tools_system_same_as_prev")),
        "calls2plus_prev_blocks_are_prefix": sum(1 for x in later if x.get("prev_blocks_are_prefix")),
        "calls2plus_first_divergence_locations": sorted({str(x.get("first_divergent_block_vs_prev")) for x in later}),
        "bash_desc_sha_call1": sorted(bash_desc_arm.get(arm, [])),
        "raw_lcp_vs_prev_min": min((x["raw_lcp_bytes_vs_prev"] for x in later), default=None),
        "raw_lcp_vs_prev_frac_of_prev_min": min((round(x["raw_lcp_bytes_vs_prev"] / x["raw_prev_bytes"], 4) for x in later), default=None),
        "call1_cache_read_values": sorted({x["call1_cache_read"] for x in ci}),
        "call1_writer_arms_for_reading_cells": sorted({a2 for x in ci if (x["call1_cache_read"] or 0) > 0 for a2 in x["call1_writer_arms"]}),
        "reading_cells_without_same_prefix_writer": [x["trial"] for x in ci if (x["call1_cache_read"] or 0) > 0 and not x["call1_writer_arms"]],
    }
    arms[arm] = a
gap = {k: round(arms["with"][k] - arms["without"][k], 4) for k in
       ("cache_usd_including_cross_cell_reads", "cache_usd_within_cell_only_call1_reads_as_writes",
        "total_usd_including_cross_cell_reads", "total_usd_within_cell_only")}
cross_arm_shared_prefix = bool({x["tools_system_sha"] for x in percall if x["arm"] == "with"} &
                               {x["tools_system_sha"] for x in percall if x["arm"] == "without"})
summary = {"method": {
    "bodies": "forwarded.bin = exact bytes sent upstream, captured by capture_run_ab.py (wrapper), not by the proxy",
    "raw_lcp": "longest common byte prefix of consecutive forwarded bodies within a cell (raw bytes; JSON key order is max_tokens, system, messages, tools, so this is byte order, not cache order)",
    "block_divergence": "first differing block in Anthropic cache order (tools -> system -> message content blocks), cache_control markers ignored",
    "call1_writer": f"an earlier call from another cell with identical tools+system and ts within {TTL}s before this cell's call 1",
    "prices": PRICES, "within_cell_only": "call-1 cache reads repriced as cache writes (what call 1 writes when nothing is cached); call 2+ reads kept"},
    "mapping_problems": problems, "cells_mapped": len(cells), "arms": arms, "with_minus_without": gap,
    "tools_system_prefix_shared_across_arms": cross_arm_shared_prefix}
# read lag: which earlier call in the same cell does each call-2+ read match, and how old was it
lag = {}
for c in cells:
    cs = c["calls"]; L = c["ledger"]
    tot = [(x.get("cache_read") or 0) + (x.get("cache_write") or 0) + (x.get("input_uncached") or 0) for x in L]
    for k in range(1, len(cs)):
        t = ts(cs[k][0]); rd = L[k].get("cache_read") or 0
        ages = [(t - ts(cs[j][0])).total_seconds() for j in range(k)]
        src = [j + 1 for j in range(k) if rd and abs(tot[j] - rd) <= 2]
        rec = {"read": rd > 0, "age_prev_s": ages[-1], "age_oldest_s": ages[0],
               "matches_call": src[-1] if src else None,
               "matched_age_s": ages[src[-1] - 1] if src else None}
        lag.setdefault(c["arm"], []).append(rec)
lag_sum = {}
for arm, recs in lag.items():
    rd = [r for r in recs if r["read"]]; miss = [r for r in recs if not r["read"]]
    lag_sum[arm] = {"calls2plus": len(recs), "reads": len(rd),
        "reads_matching_an_earlier_call_total_input": sum(1 for r in rd if r["matches_call"]),
        "matched_write_age_s_min": min((r["matched_age_s"] for r in rd if r["matched_age_s"] is not None), default=None),
        "misses_where_oldest_earlier_call_age_s_max": max((r["age_oldest_s"] for r in miss), default=None),
        "misses_with_any_earlier_call_older_than_6s": sum(1 for r in miss if r["age_oldest_s"] > 6),
        "reads_where_prev_call_age_s_le_3_read_older_call": sum(1 for r in rd if r["age_prev_s"] <= 3 and r["matches_call"])}
summary["read_lag"] = lag_sum
summary["method"]["read_lag"] = "meta ts has 1 s resolution; a read 'matches' call j when its cache_read equals call j's total input (+-2 tokens)"
json.dump(summary, open(f"{OUT}/offsets-summary.json", "w"), indent=1, sort_keys=True)
with open(f"{OUT}/offsets-per-call.jsonl", "w") as fh:
    for x in sorted(percall, key=lambda x: (x["arm"], x["trial"], x["i"])): fh.write(json.dumps(x, sort_keys=True) + "\n")
with open(f"{OUT}/cells-timeline.csv", "w", newline="") as fh:
    keys = [k for k in cellinfo[0].keys()]
    w = csv.DictWriter(fh, keys); w.writeheader()
    for x in cellinfo: w.writerow({k: (";".join(v) if isinstance(v, list) else v) for k, v in x.items()})
print(json.dumps(summary, indent=1, sort_keys=True))
