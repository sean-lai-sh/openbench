#!/usr/bin/env python3
"""Token/$ bucket breakout for a PR (vendor_split + RATES)."""
import json, glob, sys, statistics as stats
from collections import defaultdict
from thesis.ab.summarize import row_cost, billable_tokens, RATES

FIELDS = ["tokens_input_uncached", "tokens_output", "tokens_cache_read", "tokens_cache_write"]

def mean(xs):
    return sum(xs)/len(xs) if xs else float("nan")

def pct(a,b):
    if a == 0:
        return float("inf") if b else 0.0
    return (b-a)/a*100.0

def load_pr(pr):
    rows = {"without": [], "with": []}
    for side in rows:
        for p in sorted(glob.glob(f"results/ab/{pr}/cells/{side}/*/*.json")):
            try:
                rows[side].append(json.load(open(p)))
            except Exception:
                pass
    return rows

def side_means(rows):
    out = {}
    toks = [r.get("tokens") or 0 for r in rows]
    costs = [row_cost(r) for r in rows]
    costs = [c for c in costs if c is not None]
    out["n"] = len(rows)
    out["tokens"] = mean(toks)
    out["row_cost"] = mean(costs) if costs else float("nan")
    splits = []
    for r in rows:
        s = billable_tokens(r)
        if s is None:
            continue
        splits.append(s)
    out["n_split"] = len(splits)
    for f in FIELDS:
        out[f] = mean([s[f] for s in splits]) if splits else float("nan")
        out[f+"_usd"] = (out[f]/1e6)*RATES[f] if splits else float("nan")
    out["billable_sum"] = sum(out[f] for f in FIELDS) if splits else float("nan")
    out["bucket_usd_sum"] = sum(out[f+"_usd"] for f in FIELDS) if splits else float("nan")
    # by task
    by_task = defaultdict(list)
    for r in rows:
        by_task[r.get("task","?")].append(r)
    out["by_task"] = {}
    for t, rs in sorted(by_task.items()):
        splits_t = [billable_tokens(r) for r in rs]
        splits_t = [s for s in splits_t if s]
        costs_t = [c for c in (row_cost(r) for r in rs) if c is not None]
        out["by_task"][t] = {
            "tokens": mean([r.get("tokens") or 0 for r in rs]),
            "cost": mean(costs_t) if costs_t else float("nan"),
            "output": mean([s["tokens_output"] for s in splits_t]) if splits_t else float("nan"),
            "cache_read": mean([s["tokens_cache_read"] for s in splits_t]) if splits_t else float("nan"),
            "input_uncached": mean([s["tokens_input_uncached"] for s in splits_t]) if splits_t else float("nan"),
            "cache_write": mean([s["tokens_cache_write"] for s in splits_t]) if splits_t else float("nan"),
        }
    return out

def render(pr, a, b):
    lines = []
    lines.append(f"# PR #{pr} harder 5-trial: token/$ bucket breakout")
    lines.append("")
    lines.append(f"Rates ($/M): {RATES}")
    lines.append(f"Basis: vendor_split on without n={a['n']} with n={b['n']} (n_split {a['n_split']}/{b['n_split']}).")
    lines.append("`tokens` field = reported total used in prior summaries (NOT full billable sum).")
    lines.append("")
    for name, m in (("without", a), ("with", b)):
        lines.append(f"## Per-cell means")
        lines.append(f"### {name} (n={m['n']})")
        lines.append(f"- reported `tokens`: {m['tokens']:.0f}")
        lines.append(f"- row_cost: ${m['row_cost']:.4f}")
        for f in FIELDS:
            short = f.replace("tokens_","")
            lines.append(f"- {short}: {m[f]:.0f} tok → ${m[f+'_usd']:.4f}")
        lines.append(f"- sum bucket $: ${m['bucket_usd_sum']:.4f}")
        lines.append("")
    # fix duplicate headers - rewrite cleaner
    return "\n".join(lines)

def render_full(pr, a, b):
    L = []
    L.append(f"# PR #{pr} harder 5-trial: token/$ bucket breakout")
    L.append("")
    L.append(f"Rates ($/M): {RATES}")
    L.append(f"Basis: vendor_split on without n={a['n']} with n={b['n']} (n_split {a['n_split']}/{b['n_split']}).")
    L.append("`tokens` field = reported total used in prior summaries (NOT full billable sum).")
    L.append("")
    L.append("## Per-cell means")
    for name, m in (("without", a), ("with", b)):
        L.append(f"### {name} (n={m['n']})")
        L.append(f"- reported `tokens`: {m['tokens']:.0f}")
        L.append(f"- row_cost: ${m['row_cost']:.4f}")
        for f in FIELDS:
            short = f.replace("tokens_","")
            L.append(f"- {short}: {m[f]:.0f} tok → ${m[f+'_usd']:.4f}")
        L.append(f"- sum bucket $: ${m['bucket_usd_sum']:.4f}")
        L.append("")
    L.append("## Deltas (with − without)")
    L.append(f"- reported tokens: {a['tokens']:.0f}→{b['tokens']:.0f} ({pct(a['tokens'],b['tokens']):+.1f}%)")
    L.append(f"- cost: ${a['row_cost']:.4f}→${b['row_cost']:.4f} ({pct(a['row_cost'],b['row_cost']):+.1f}%)")
    L.append("")
    L.append(f"- sum of billable buckets: {a['billable_sum']:.0f}→{b['billable_sum']:.0f} ({pct(a['billable_sum'],b['billable_sum']):+.1f}%)")
    L.append("")
    for f in FIELDS:
        short = f.replace("tokens_","")
        L.append(
            f"- {short}: {a[f]:.0f}→{b[f]:.0f} tok ({pct(a[f],b[f]):+.1f}%); "
            f"${a[f+'_usd']:.4f}→${b[f+'_usd']:.4f} ({pct(a[f+'_usd'],b[f+'_usd']):+.1f}%)"
        )
    L.append("")
    L.append("## $ share of cell cost")
    for name, m in (("without", a), ("with", b)):
        parts = []
        for f in FIELDS:
            short = f.replace("tokens_","")
            share = (m[f+"_usd"]/m["row_cost"]*100) if m["row_cost"] else 0
            parts.append(f"{short} {share:.1f}%")
        L.append(f"- {name}: " + ", ".join(parts))
    L.append("")
    L.append("## Per-task (reported tok Δ% | cost Δ% | output Δ% | input_uncached Δ% | cache_read Δ% | cache_write Δ%)")
    tasks = sorted(set(a["by_task"]) | set(b["by_task"]))
    for t in tasks:
        ta, tb = a["by_task"].get(t), b["by_task"].get(t)
        if not ta or not tb:
            continue
        L.append(
            f"- {t}: tok {pct(ta['tokens'],tb['tokens']):+.1f}% | cost {pct(ta['cost'],tb['cost']):+.1f}% | "
            f"out {pct(ta['output'],tb['output']):+.1f}% | in_u {pct(ta['input_uncached'],tb['input_uncached']):+.1f}% | "
            f"cache_r {pct(ta['cache_read'],tb['cache_read']):+.1f}% | cache_w {pct(ta['cache_write'],tb['cache_write']):+.1f}%"
        )
    L.append("")
    L.append("## $ delta attribution")
    dcost = b["row_cost"] - a["row_cost"]
    contrib_sum = 0.0
    for f in FIELDS:
        short = f.replace("tokens_","")
        d = b[f+"_usd"] - a[f+"_usd"]
        contrib_sum += d
        share = (d/dcost*100) if dcost else 0
        L.append(f"- {short}: ${d:+.4f} ({share:.0f}% of Δcost)")
    L.append(f"- sum contrib ${contrib_sum:+.4f} vs Δcost ${dcost:+.4f}")
    # primary metrics line
    L.append("")
    L.append("## Primary metrics (means)")
    L.append(f"- output tokens: {a['tokens_output']:.0f}→{b['tokens_output']:.0f} ({pct(a['tokens_output'],b['tokens_output']):+.1f}%)")
    L.append(f"- input_uncached: {a['tokens_input_uncached']:.0f}→{b['tokens_input_uncached']:.0f} ({pct(a['tokens_input_uncached'],b['tokens_input_uncached']):+.1f}%)")
    return "\n".join(L) + "\n"

def main():
    if len(sys.argv) < 2:
        print("usage: hard5_buckets.py PR", file=sys.stderr)
        sys.exit(2)
    pr = sys.argv[1]
    rows = load_pr(pr)
    a, b = side_means(rows["without"]), side_means(rows["with"])
    text = render_full(pr, a, b)
    out = Path_out = f"results/ab-logs/hard5-{pr}-token-cost-buckets.md"
    open(out,"w").write(text)
    print(out)
    print(text)

if __name__ == "__main__":
    from pathlib import Path
    main()
