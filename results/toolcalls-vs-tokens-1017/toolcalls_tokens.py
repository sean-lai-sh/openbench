#!/usr/bin/env python3
"""Do fewer tool calls go with lower token cost? Read-only analysis of stored 30/side cells.

Run from the repo root:  python3 results/toolcalls-vs-tokens-1017/toolcalls_tokens.py
Pure stdlib. Uses thesis/ab/evidence.py for tool calls:
  * OpenCode: transcript_files + evidence_files, then _metric_calls(paths, all) — the same
    authoritative, deduplicated call list the runner's read/edit/bash counts use
    (sqlite/WAL dedupe, per-call storage merge, or the richest single transcript).
    Subagent (child-session) calls are included, like the token totals.
  * Oh My Pi: the _pi_stream_events/_pi_messages path with _pi_tool_calls' id dedupe,
    but without its read/edit/write/bash name filter, so every toolCall counts.
Tokens follow the step-3/4/6 stats.py (boot.py tok): input_uncached + output + cache_read +
cache_write, all proxy requests. Scored cells = failure_class not in
(infra, rate_limited, stalled, incompatible), as in stats.py. Token and tool-call % changes are
ratios of side means with the same percentile bootstrap (10k, random.Random(0)) as boot.py.
Per-request context comes from each run's proxy-ledger, joined to cells by their exact
requests_* totals.
"""
from __future__ import annotations

import collections
import csv
import glob
import json
import math
import os
import random
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, os.getcwd())
from thesis.ab import evidence as E  # noqa: E402

R = "results"
OUT = os.path.join(R, "toolcalls-vs-tokens-1017")
EX = ("infra", "rate_limited", "stalled", "incompatible")

# Step-3 canonical seeded dirs, identical to #89 (results/step3-sonnet-1016-firstside-fisher).
STEP3 = {
    "step3-sonnet-1016": ["11731", "12214", "13090", "13198", "13269", "17053", "17098",
                          "19058", "2334", "2367", "26821", "3052", "3115", "3369", "4204",
                          "5131", "5140", "6524"],
    "step3-sonnet-1016-reorder": ["623", "913", "984", "1248", "5066"],
    "step3-sonnet-1016-13331-rebuild": ["13331"],
    "step3-sonnet-1016-23771-lsp": ["23771"],
    "step3-sonnet-1016-4838-dropblock": ["4838"],
    "step3-sonnet-1016-make-rebuild2": ["21070", "22390", "24974", "25226", "25431"],
}
RUNS = []  # (group, harness, run_dir, pr, base_side, treat_side)
for d, prs in STEP3.items():
    for pr in prs:
        RUNS.append(("step3-sonnet", "opencode", f"{R}/{d}", pr, "without", "with"))
for pr in ("913", "3052", "13331", "24974", "25226", "26821"):
    RUNS.append(("step6-opus", "opencode", f"{R}/step6-opus-1017-{pr}", pr, "without", "with"))
for pr in ("omp-15", "omp-16", "omp-21", "omp-28", "omp-33", "omp-35"):
    RUNS.append(("step4-omp-sonnet", "omp", f"{R}/step4-omp-sonnet-1017", pr, "without", "with"))
RUNS.append(("step5-aa-opus", "opencode", f"{R}/step5-opus-aa-1017-oc26821-aa", "26821", "aa-1", "aa-2"))
RUNS.append(("step5-aa-opus", "omp", f"{R}/step5-opus-aa-1017-omp36-aa", "omp-36", "aa-1", "aa-2"))
RUNS.append(("step2-aa-sonnet", "opencode", f"{R}/aa-sonnet-1016/oc26821-aa", "26821", "aa-1", "aa-2"))
RUNS.append(("step2-aa-sonnet", "omp", f"{R}/aa-sonnet-1016/omp36-aa", "omp-36", "aa-1", "aa-2"))

EFFECT_ROWS = [("step3-sonnet", "3052"), ("step6-opus", "3052"), ("step3-sonnet", "13331"),
               ("step6-opus", "13331"), ("step3-sonnet", "26821"), ("step6-opus", "26821"),
               ("step3-sonnet", "913"), ("step6-opus", "913"), ("step4-omp-sonnet", "omp-16")]

TYPE = {
    "read": "read", "view": "read",
    "edit": "edit", "multiedit": "edit", "write": "edit", "patch": "edit", "apply_patch": "edit",
    "bash": "bash", "shell": "bash",
    "grep": "search", "glob": "search", "list": "search", "ls": "search", "find": "search",
    "codesearch": "search", "search": "search", "websearch": "search", "lsp": "search",
}
TYPES = ("read", "edit", "bash", "search", "other")
TITLE_MAX = 3000


def tok(r):
    return sum((r.get(k) or 0) for k in ("tokens_input_uncached", "tokens_output", "tokens_cache_read", "tokens_cache_write"))


def boot(a, b, n=10000, seed=0):
    rnd = random.Random(seed)
    m = lambda x: sum(x) / len(x)
    out = []
    for _ in range(n):
        ma = m([rnd.choice(a) for _ in a])
        mb = m([rnd.choice(b) for _ in b])
        out.append(mb / ma - 1 if ma else float("nan"))
    out = sorted(x for x in out if x == x)
    if not out or m(a) == 0:
        return float("nan"), float("nan"), float("nan")
    k = len(out)
    return m(b) / m(a) - 1, out[int(.025 * k)], out[int(.975 * k) - 1]


def ranks(x):
    order = sorted(range(len(x)), key=lambda i: x[i])
    r = [0.0] * len(x)
    i = 0
    while i < len(x):
        j = i
        while j + 1 < len(x) and x[order[j + 1]] == x[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def pearson(x, y):
    n = len(x)
    if n < 3:
        return float("nan")
    mx, my = sum(x) / n, sum(y) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sx = math.sqrt(sum((a - mx) ** 2 for a in x))
    sy = math.sqrt(sum((b - my) ** 2 for b in y))
    return sxy / (sx * sy) if sx and sy else float("nan")


def t_sf2(t, df):
    """Two-sided p for Student t via regularized incomplete beta (continued fraction)."""
    x = df / (df + t * t)
    a, b = df / 2, 0.5

    def betacf(a, b, x):
        qab, qap, qam = a + b, a + 1, a - 1
        c, d = 1.0, 1 - qab * x / qap
        d = 1 / (d if abs(d) > 1e-300 else 1e-300)
        h = d
        for m in range(1, 300):
            m2 = 2 * m
            aa = m * (b - m) * x / ((qam + m2) * (a + m2))
            d = 1 + aa * d; d = 1 / (d if abs(d) > 1e-300 else 1e-300)
            c = 1 + aa / c if abs(c) > 1e-300 else 1e300
            h *= d * c
            aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
            d = 1 + aa * d; d = 1 / (d if abs(d) > 1e-300 else 1e-300)
            c = 1 + aa / c if abs(c) > 1e-300 else 1e300
            de = d * c
            h *= de
            if abs(de - 1) < 1e-12:
                break
        return h
    lbt = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    if x < (a + 1) / (a + b + 2):
        ib = math.exp(lbt) * betacf(a, b, x) / a
    else:
        ib = 1 - math.exp(lbt) * betacf(b, a, 1 - x) / b
    return min(1.0, max(0.0, ib))


def spearman(x, y):
    rho = pearson(ranks(x), ranks(y))
    n = len(x)
    if rho != rho or n < 4:
        return rho, float("nan"), n
    if abs(rho) >= 1:
        return rho, 0.0, n
    t = rho * math.sqrt((n - 2) / (1 - rho * rho))
    return rho, t_sf2(t, n - 2), n


def paths_for(out_dir, pr, side, task, trial, row):
    out = Path(out_dir)
    fs = E.transcript_files(out, pr, side, task, trial, row) + E.evidence_files(out, pr, side, task, trial)
    seen, uniq = set(), []
    for f in fs:
        k = f.resolve()
        if k not in seen:
            seen.add(k)
            uniq.append(f)
    return uniq


def pi_all_calls(paths):
    events = E._pi_stream_events(paths)
    if events is None:
        return None
    seen, names = set(), []
    for event in events:
        for message in E._pi_messages(event):
            if message.get("role") != "assistant" or not isinstance(message.get("content"), list):
                continue
            for part in message["content"]:
                if not isinstance(part, dict) or part.get("type") != "toolCall":
                    continue
                name = str(part.get("name") or "")
                ident = part.get("id")
                args = part.get("arguments")
                fwd = args if isinstance(args, str) else json.dumps(args if isinstance(args, dict) else {}, sort_keys=True)
                key = ident if isinstance(ident, str) and ident else f"{name}:{fwd}"
                if key in seen:
                    continue
                seen.add(key)
                names.append(name)
    return names


_TI = re.compile(r'"toolCallId"\s*:\s*"([^"]+)"\s*,\s*"toolName"\s*:\s*"([^"]+)"|"toolName"\s*:\s*"([^"]+)"\s*,\s*"toolCallId"\s*:\s*"([^"]+)"')


def tool_invocation_calls(paths):
    """Fallback for the old OpenCode storage (``"type":"tool-invocation"`` parts with
    toolCallId/toolName, e.g. the 623 build), which evidence.py's call parser does not read.
    One toolCallId counts once across all files."""
    seen, names = set(), []
    for path in paths:
        text = E._read_text(path)
        if not text or "tool-invocation" not in text:
            continue
        for m in _TI.finditer(text):
            cid, name = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
            if cid in seen:
                continue
            seen.add(cid)
            names.append(name)
    return names


def ledger_index(run_dir):
    idx = collections.defaultdict(list)
    for f in glob.glob(f"{run_dir}/proxy-ledger/*.jsonl"):
        reqs = []
        for line in open(f):
            if not line.strip():
                continue
            r = json.loads(line)
            u = r.get("usage") or {}
            reqs.append(((u.get("input_tokens") or 0), (u.get("cache_read_input_tokens") or 0),
                         (u.get("cache_creation_input_tokens") or 0), (u.get("output_tokens") or 0)))
        key = (len(reqs), sum(q[0] for q in reqs), sum(q[1] for q in reqs), sum(q[2] for q in reqs), sum(q[3] for q in reqs))
        idx[key].append(reqs)
    return idx


def collect():
    cells = []
    unmatched = collections.Counter()
    ledgers = {}
    for group, harness, run_dir, pr, base, treat in RUNS:
        if run_dir not in ledgers:
            ledgers[run_dir] = ledger_index(run_dir)
        L = ledgers[run_dir]
        for side in (base, treat):
            for p in sorted(glob.glob(f"{run_dir}/{pr}/cells/{side}/*/*.json")):
                r = json.load(open(p))
                if r.get("failure_class") in EX:
                    continue
                task, trial = str(r.get("task")), int(r.get("trial"))
                ps = paths_for(run_dir, pr, side, task, trial, r)
                names = pi_all_calls(ps) if harness == "omp" else None
                mode = "pi"
                if names is None:
                    mode, _ = E._authoritative_calls(ps)
                    names = [c.tool for c in E._metric_calls(ps, lambda _c: True)]
                    if not names:
                        fb = tool_invocation_calls(ps)
                        if fb:
                            mode, names = "tool-invocation", fb
                bytype = collections.Counter(TYPE.get(n, "other") for n in names)
                key = (r.get("requests_count"), r.get("requests_input_uncached"), r.get("requests_cache_read"),
                       r.get("requests_cache_write"), r.get("requests_output"))
                reqs = L.get(key)
                ctx = [q[0] + q[1] + q[2] for q in reqs[0]] if reqs else None
                # OpenCode's session-title request is tiny (252-1,900 context tokens, ~17 output);
                # "main" requests are the agent turns (>= 3,000 context tokens).
                main_ctx = [x for x in ctx if x >= TITLE_MAX] if ctx else None
                if reqs is None:
                    unmatched[(group, pr)] += 1
                inp = sum((r.get(k) or 0) for k in ("tokens_input_uncached", "tokens_cache_read", "tokens_cache_write"))
                cells.append(dict(
                    group=group, harness=harness, model=r.get("upstream_model") or "", pr=pr, side=side,
                    arm="base" if side == base else "treat", task=task, trial=trial,
                    failure_class=r.get("failure_class"), evidence_mode=mode, evidence_files=len(ps),
                    tool_calls=len(names), **{f"tc_{t}": bytype.get(t, 0) for t in TYPES},
                    other_tools=";".join(sorted({n for n in names if TYPE.get(n, "other") == "other"})),
                    row_read_calls=r.get("read_calls"), row_edit_calls=r.get("edit_calls"),
                    turns=r.get("turns"), requests=r.get("requests_count"),
                    tokens=tok(r), input_tokens=inp, output_tokens=r.get("tokens_output") or 0,
                    small_requests=(len(ctx) - len(main_ctx)) if ctx else "",
                    first_req_ctx=main_ctx[0] if main_ctx else "", max_req_ctx=max(ctx) if ctx else "",
                    mean_req_ctx=round(sum(main_ctx) / len(main_ctx), 1) if main_ctx else "",
                ))
    return cells, unmatched


def mean_nn(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.mean(xs), 2) if xs else ""


def pct(v):
    return "nan" if v != v else f"{100 * v:+.1f}%"


def main():
    cells, unmatched = collect()
    keys = ["group", "harness", "model", "pr", "side", "arm", "task", "trial", "failure_class", "evidence_mode",
            "evidence_files", "tool_calls"] + [f"tc_{t}" for t in TYPES] + [
            "other_tools", "row_read_calls", "row_edit_calls", "turns", "requests", "tokens", "input_tokens", "output_tokens",
            "small_requests", "first_req_ctx", "max_req_ctx", "mean_req_ctx"]
    with open(os.path.join(OUT, "cells.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(cells)

    rows = collections.OrderedDict()
    for c in cells:
        rows.setdefault((c["group"], c["pr"]), []).append(c)
    per = []
    for (group, pr), cs in rows.items():
        a = [c for c in cs if c["arm"] == "base"]
        b = [c for c in cs if c["arm"] == "treat"]
        g = lambda xs, k: [x[k] for x in xs]
        tk = boot(g(a, "tokens"), g(b, "tokens"))
        tc = boot(g(a, "tool_calls"), g(b, "tool_calls"))
        rq = boot(g(a, "requests"), g(b, "requests"))
        rho, p, n = spearman(g(cs, "tool_calls"), g(cs, "tokens"))
        rec = dict(group=group, harness=cs[0]["harness"], model=cs[0]["model"], pr=pr,
                   sides=f"{a[0]['side']}->{b[0]['side']}", n_base=len(a), n_treat=len(b),
                   tc_median_base=statistics.median(g(a, "tool_calls")), tc_median_treat=statistics.median(g(b, "tool_calls")),
                   tc_mean_base=round(statistics.mean(g(a, "tool_calls")), 2), tc_mean_treat=round(statistics.mean(g(b, "tool_calls")), 2),
                   tc_pct=tc[0], tc_lo=tc[1], tc_hi=tc[2],
                   tok_mean_base=round(statistics.mean(g(a, "tokens"))), tok_mean_treat=round(statistics.mean(g(b, "tokens"))),
                   tok_pct=tk[0], tok_lo=tk[1], tok_hi=tk[2],
                   req_pct=rq[0], req_lo=rq[1], req_hi=rq[2],
                   turns_mean_base=mean_nn(g(a, "turns")), turns_mean_treat=mean_nn(g(b, "turns")),
                   turns_missing=sum(1 for c in cs if c["turns"] is None),
                   input_mean_base=round(statistics.mean(g(a, "input_tokens"))), input_mean_treat=round(statistics.mean(g(b, "input_tokens"))),
                   output_mean_base=round(statistics.mean(g(a, "output_tokens"))), output_mean_treat=round(statistics.mean(g(b, "output_tokens"))),
                   **{f"{t}_mean_base": round(statistics.mean(g(a, f"tc_{t}")), 2) for t in TYPES},
                   **{f"{t}_mean_treat": round(statistics.mean(g(b, f"tc_{t}")), 2) for t in TYPES},
                   within_rho=rho, within_p=p)
        tok_sig = not (rec["tok_lo"] <= 0 <= rec["tok_hi"])
        tc_sig = rec["tc_lo"] == rec["tc_lo"] and not (rec["tc_lo"] <= 0 <= rec["tc_hi"])
        rec["tok_ci_excl0"], rec["tc_ci_excl0"] = tok_sig, tc_sig
        if tok_sig and not tc_sig:
            rec["pattern"] = "tokens move, tool calls flat"
        elif tc_sig and not tok_sig:
            rec["pattern"] = "tool calls move, tokens flat"
        elif tok_sig and tc_sig:
            rec["pattern"] = "same direction" if (rec["tok_pct"] > 0) == (rec["tc_pct"] > 0) else "OPPOSITE directions"
        else:
            rec["pattern"] = "both flat"
        per.append(rec)
    pk = list(per[0].keys())
    with open(os.path.join(OUT, "per_pr.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=pk)
        w.writeheader()
        for rec in per:
            w.writerow({k: (f"{v:.4f}" if isinstance(v, float) else v) for k, v in rec.items()})

    lines = []
    P = lines.append
    P(f"scored cells: {len(cells)}; rows (PR x model x run): {len(per)}; ledger-unmatched cells: {sum(unmatched.values())} {dict(unmatched)}")
    P("evidence modes: " + str(collections.Counter(c["evidence_mode"] for c in cells)))
    P("cells with 0 tool calls: " + str(sum(1 for c in cells if c["tool_calls"] == 0)))
    rc = [c for c in cells if c["row_read_calls"] is not None]
    P(f"check vs runner's stored read_calls: {sum(1 for c in rc if c['tc_read'] == c['row_read_calls'])}/{len(rc)} cells equal; "
      f"edit_calls (edit+multiedit+write here vs runner edit/multiedit): {sum(1 for c in cells if c['row_edit_calls'] is not None and c['tc_edit'] >= c['row_edit_calls'])}/"
      f"{sum(1 for c in cells if c['row_edit_calls'] is not None)} cells >= stored")
    P("other tools seen: " + str(collections.Counter(n for c in cells for n in c["other_tools"].split(";") if n)))
    # pooled Spearman
    corr = []
    for label, sel in [("ALL", cells),
                       ("OpenCode", [c for c in cells if c["harness"] == "opencode"]),
                       ("Oh My Pi", [c for c in cells if c["harness"] == "omp"]),
                       ("Sonnet", [c for c in cells if c["model"] == "claude-sonnet-5-5"]),
                       ("Opus", [c for c in cells if c["model"] == "claude-opus-5-5"])]:
        for ylab in ("tokens", "requests", "input_tokens", "output_tokens"):
            rho, p, n = spearman([c["tool_calls"] for c in sel], [c[ylab] for c in sel])
            corr.append((label, "tool_calls", ylab, rho, p, n))
        rho, p, n = spearman([c["requests"] for c in sel], [c["tokens"] for c in sel])
        corr.append((label, "requests", "tokens", rho, p, n))
    # within-PR: ranks within each row, pooled; plus distribution of per-row rho
    def within(sel_rows, xk="tool_calls", yk="tokens"):
        xs, ys = [], []
        for (gp, pr), cs in rows.items():
            if (gp, pr) not in sel_rows:
                continue
            rx, ry = ranks([c[xk] for c in cs]), ranks([c[yk] for c in cs])
            n = len(cs)
            xs += [(v - (n + 1) / 2) / n for v in rx]
            ys += [(v - (n + 1) / 2) / n for v in ry]
        return pearson(xs, ys), len(xs)
    allrows = set(rows)
    w_all = within(allrows)
    w_oc = within({k for k in rows if rows[k][0]["harness"] == "opencode"})
    w_omp = within({k for k in rows if rows[k][0]["harness"] == "omp"})
    rhos = [r["within_rho"] for r in per if r["within_rho"] == r["within_rho"]]
    P("")
    P("Spearman across cells (pooled):")
    for c in corr:
        P(f"  {c[0]:9s} {c[1]} vs {c[2]}: rho={c[3]:+.3f} p={c[4]:.2g} n={c[5]}")
    P(f"Within-PR (ranks centred within each row, pooled): all rho={w_all[0]:+.3f} n={w_all[1]}; OpenCode {w_oc[0]:+.3f}; Oh My Pi {w_omp[0]:+.3f}")
    P(f"Per-row within-PR Spearman: {len(rhos)} rows with variation; median {statistics.median(rhos):+.3f}; "
      f">0 in {sum(1 for r in rhos if r > 0)}, <0 in {sum(1 for r in rhos if r < 0)}; "
      f"p<0.05 positive {sum(1 for r in per if r['within_rho'] == r['within_rho'] and r['within_p'] < 0.05 and r['within_rho'] > 0)}, "
      f"negative {sum(1 for r in per if r['within_rho'] == r['within_rho'] and r['within_p'] < 0.05 and r['within_rho'] < 0)}")
    # across PRs
    P("")
    P("Across rows: % change in tool calls (mean ratio) vs % change in tokens:")
    for label, sel in [("all rows", per), ("A/B rows only (no A/A)", [r for r in per if "aa" not in r["group"]]),
                       ("OpenCode A/B", [r for r in per if "aa" not in r["group"] and r["harness"] == "opencode"]),
                       ("Oh My Pi A/B", [r for r in per if "aa" not in r["group"] and r["harness"] == "omp"])]:
        sel = [r for r in sel if r["tc_pct"] == r["tc_pct"]]
        x = [r["tc_pct"] for r in sel]; y = [r["tok_pct"] for r in sel]
        rho, p, n = spearman(x, y)
        lx = [math.log1p(v) for v in x]; ly = [math.log1p(v) for v in y]
        P(f"  {label}: Spearman rho={rho:+.3f} p={p:.2g} n={n}; Pearson on log ratios r={pearson(lx, ly):+.3f}")
        rho2, p2, _ = spearman([r["req_pct"] for r in sel], y)
        P(f"     (requests % vs tokens %: Spearman rho={rho2:+.3f} p={p2:.2g})")
    P("")
    P("Rows where tokens and tool calls disagree (95% bootstrap CIs):")
    for r in per:
        if r["pattern"] in ("tokens move, tool calls flat", "tool calls move, tokens flat", "OPPOSITE directions"):
            P(f"  {r['group']:16s} {r['pr']:7s} {r['pattern']:30s} tool calls {pct(r['tc_pct'])} [{pct(r['tc_lo'])}, {pct(r['tc_hi'])}] "
              f"(median {r['tc_median_base']}->{r['tc_median_treat']}); tokens {pct(r['tok_pct'])} [{pct(r['tok_lo'])}, {pct(r['tok_hi'])}]; requests {pct(r['req_pct'])}")
    P("Rows where both move in the same direction:")
    for r in per:
        if r["pattern"] == "same direction":
            P(f"  {r['group']:16s} {r['pr']:7s} tool calls {pct(r['tc_pct'])} [{pct(r['tc_lo'])}, {pct(r['tc_hi'])}]; tokens {pct(r['tok_pct'])} [{pct(r['tok_lo'])}, {pct(r['tok_hi'])}]")
    P("Pattern counts: " + str(collections.Counter(r["pattern"] for r in per)))

    # decomposition
    P("")
    P("Decomposition (side means; log ratio identity ln T = ln R + ln(T/R); T/R = tokens per request):")
    dec = []
    for gp, pr in EFFECT_ROWS:
        cs = rows.get((gp, pr))
        if not cs:
            continue
        a = [c for c in cs if c["arm"] == "base"]; b = [c for c in cs if c["arm"] == "treat"]
        m = lambda xs, k: sum(x[k] for x in xs) / len(xs)
        Ta, Tb, Ra, Rb = m(a, "tokens"), m(b, "tokens"), m(a, "requests"), m(b, "requests")
        Ca, Cb = m(a, "tool_calls"), m(b, "tool_calls")
        Ia, Ib, Oa, Ob = m(a, "input_tokens"), m(b, "input_tokens"), m(a, "output_tokens"), m(b, "output_tokens")
        la = [c for c in a if c["first_req_ctx"] != ""]; lb = [c for c in b if c["first_req_ctx"] != ""]
        Fa, Fb = (m(la, "first_req_ctx") if la else float("nan")), (m(lb, "first_req_ctx") if lb else float("nan"))
        Ma, Mb = (m(la, "mean_req_ctx") if la else float("nan")), (m(lb, "mean_req_ctx") if lb else float("nan"))
        lt = math.log(Tb / Ta); lr = math.log(Rb / Ra); lc = math.log((Tb / Rb) / (Ta / Ra))
        # input per request split: base prompt (first request) vs growth (mean minus first)
        Ga = Ma - Fa; Gb = Mb - Fb
        rec = dict(row=f"{gp} {pr}", model=cs[0]["model"], tokens_base=round(Ta), tokens_treat=round(Tb), tok_pct=Tb / Ta - 1,
                   tool_calls_base=round(Ca, 2), tool_calls_treat=round(Cb, 2), tc_pct=Cb / Ca - 1 if Ca else float("nan"),
                   requests_base=round(Ra, 2), requests_treat=round(Rb, 2), req_pct=Rb / Ra - 1,
                   tok_per_req_base=round(Ta / Ra), tok_per_req_treat=round(Tb / Rb), tpr_pct=(Tb / Rb) / (Ta / Ra) - 1,
                   share_from_requests=lr / lt if lt else float("nan"), share_from_per_request=lc / lt if lt else float("nan"),
                   input_base=round(Ia), input_treat=round(Ib), output_base=round(Oa), output_treat=round(Ob),
                   d_input=round(Ib - Ia), d_output=round(Ob - Oa),
                   first_req_ctx_base=round(Fa) if Fa == Fa else "", first_req_ctx_treat=round(Fb) if Fb == Fb else "",
                   mean_main_ctx_base=round(Ma) if Ma == Ma else "", mean_main_ctx_treat=round(Mb) if Mb == Mb else "",
                   growth_per_req_base=round(Ga) if Ga == Ga else "", growth_per_req_treat=round(Gb) if Gb == Gb else "",
                   ledger_cells=f"{len(la)}/{len(a)},{len(lb)}/{len(b)}")
        dec.append(rec)
        P(f"  {rec['row']:24s} T {round(Ta)}->{round(Tb)} ({pct(rec['tok_pct'])}); tool calls {Ca:.2f}->{Cb:.2f} ({pct(rec['tc_pct'])}); "
          f"requests {Ra:.2f}->{Rb:.2f} ({pct(rec['req_pct'])}); tok/request {round(Ta/Ra)}->{round(Tb/Rb)} ({pct(rec['tpr_pct'])}); "
          f"share of log change: requests {rec['share_from_requests']:.0%}, per-request {rec['share_from_per_request']:.0%}; "
          f"d_input {round(Ib-Ia):+d}, d_output {round(Ob-Oa):+d}; first agent request context {rec['first_req_ctx_base']}->{rec['first_req_ctx_treat']}; "
          f"mean agent request context {rec['mean_main_ctx_base']}->{rec['mean_main_ctx_treat']} (growth over first {rec['growth_per_req_base']}->{rec['growth_per_req_treat']})")
    with open(os.path.join(OUT, "decomposition.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(dec[0].keys()))
        w.writeheader()
        for rec in dec:
            w.writerow({k: (f"{v:.4f}" if isinstance(v, float) else v) for k, v in rec.items()})
    with open(os.path.join(OUT, "correlations.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["subset", "x", "y", "spearman_rho", "p", "n"])
        for c in corr:
            w.writerow([c[0], c[1], c[2], f"{c[3]:.4f}", f"{c[4]:.3g}", c[5]])
        w.writerow(["within-PR all (centred ranks)", "tool_calls", "tokens", f"{w_all[0]:.4f}", "", w_all[1]])
        w.writerow(["within-PR OpenCode", "tool_calls", "tokens", f"{w_oc[0]:.4f}", "", ""])
        w.writerow(["within-PR Oh My Pi", "tool_calls", "tokens", f"{w_omp[0]:.4f}", "", ""])
    text = "\n".join(lines)
    open(os.path.join(OUT, "output.txt"), "w").write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
