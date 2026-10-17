#!/usr/bin/env python3
"""Step-3 Sonnet first-side miss test (read-only analysis of stored cells).

Question: in step-3 Sonnet cells run with --order interleave-seeded --seed 1016,
does the side launched first in each trial block miss (wrong_answer / hang /
timeout, i.e. judged and not success) more often than the side launched second?

Definitions mirror the runner and step-3 stats.py:
  * first side per PR = thesis/ab/run_ab.py first_side_for(1016, pr, sides)
    = sorted(sides)[sha256("1016|first-side|<pr>")[0] % 2]; recorded per cell
    as `first_side`. A cell is "first" when side == first_side. Within each
    trial block (pr, task, trial) the first side gets the lower schedule_index.
  * judged = failure_class not in (infra, rate_limited, stalled, incompatible)
    (same EX tuple as results/step3-sonnet-1016/stats.py); solved = success.
  * miss = judged and not success.
Pure stdlib (no scipy in .venv): exact Fisher, Mantel-Haenszel, CMH chi-square,
and an exact conditional (stratified) test by convolving hypergeometrics.

Run from the repo root:  python3 results/step3-sonnet-1016-firstside-fisher/firstside_fisher.py
"""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import math
import os
import sys

R = "results"
OUT = os.path.join(R, "step3-sonnet-1016-firstside-fisher")
SEED = 1016
EX = ("infra", "rate_limited", "stalled", "incompatible")
SIDES = ("with", "without")

# Canonical (scored) seeded-order data dir for every step-3 Sonnet PR.
CANON = {
    "step3-sonnet-1016": ["11731", "12214", "13090", "13198", "13269", "17053", "17098",
                          "19058", "2334", "2367", "26821", "3052", "3115", "3369", "4204",
                          "5131", "5140", "6524"],
    "step3-sonnet-1016-reorder": ["623", "913", "984", "1248", "5066"],
    "step3-sonnet-1016-13331-rebuild": ["13331"],
    "step3-sonnet-1016-23771-lsp": ["23771"],
    "step3-sonnet-1016-4838-dropblock": ["4838"],
    "step3-sonnet-1016-make-rebuild2": ["21070", "22390", "24974", "25226", "25431"],
}
# Seeded-order runs that were superseded (not scored); used only in a sensitivity.
SUPERSEDED_SEEDED = {
    "step3-sonnet-1016": ["5066", "4838"],          # batch3 5066 (re-run in -reorder); 4838 27/30+30/30 infra
    "step3-sonnet-1016-make-rebuild2": ["23771"],   # 2+2 timeout cells, no C# LSP (re-run in -23771-lsp)
}
# Seeded-order dirs with no usable judged data (reported, never pooled).
INFRA_ONLY_SEEDED = {
    "step3-sonnet-1016-tempfail": "Vertex 400 temperature (pre-#49 strip); 11731/12214/13090 re-run",
    "step3-sonnet-1016-make-rebuild": "auth failure, all cells infra",
    "step3-sonnet-1016-authsmoke": "1-trial smoke (5066)",
    "step3-sonnet-1016-23771-lsp-smoke": "1-trial smoke (23771)",
    "step3-sonnet-1016-quarantine": "quarantined cells (unmetered / 401 ADC), README.txt",
}
# Not seeded order: excluded from the primary test, listed in the report.
NOT_SEEDED = {
    ("step3-sonnet-1016", "623"): "OLD ORDER --order interleave (without always first)",
    ("step3-sonnet-1016", "913"): "OLD ORDER --order interleave (without always first)",
    ("step3-sonnet-1016", "984"): "OLD ORDER --order interleave (without always first)",
    ("step3-sonnet-1016", "1248"): "OLD ORDER --order interleave (without always first)",
    ("step3-sonnet-1016-oldorder-partial", "2334"): "OLD ORDER --order interleave, partial",
    ("step3-sonnet-1016-sidesorder-aborted", "623"): "--order sides (block order), aborted",
    ("step3-sonnet-1016-sidesorder-aborted", "913"): "--order sides (block order), aborted",
    ("step3-sonnet-1016-sidesorder-aborted", "984"): "--order sides (block order), aborted",
}


def first_side_for(seed: int, pr: str, sides) -> str:
    digest = hashlib.sha256(f"{int(seed)}|first-side|{pr}".encode("utf-8")).digest()
    return sorted(sides)[digest[0] % len(sides)]


def load(d: str, pr: str) -> list[dict]:
    rows = []
    for side in SIDES:
        p = os.path.join(R, d, pr, f"{side}.jsonl")
        if not os.path.exists(p):
            continue
        for line in open(p):
            if line.strip():
                r = json.loads(line)
                r["_side"] = side
                r["_dir"] = d
                r["_pr"] = pr
                rows.append(r)
    return rows


# ---------------------------------------------------------------- statistics
def lchoose(n, k):
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def hyper_pmf(n1, n2, m1):
    """pmf over a = misses among first-side cells, margins n1 (first), n2, m1 (misses)."""
    lo, hi = max(0, m1 - n2), min(n1, m1)
    den = lchoose(n1 + n2, m1)
    return {a: math.exp(lchoose(n1, a) + lchoose(n2, m1 - a) - den) for a in range(lo, hi + 1)}


def two_sided(pmf: dict, obs: int) -> float:
    p0 = pmf[obs]
    return min(1.0, sum(p for p in pmf.values() if p <= p0 * (1 + 1e-7)))


def fisher(a, b, c, d):
    """2x2 [[a,b],[c,d]] rows = first/second, cols = miss/solved. Two-sided + one-sided (first misses more)."""
    pmf = hyper_pmf(a + b, c + d, a + c)
    return two_sided(pmf, a), sum(p for k, p in pmf.items() if k >= a)


def odds_ratio(a, b, c, d):
    if 0 in (a, b, c, d):
        a, b, c, d = a + .5, b + .5, c + .5, d + .5
    orr = (a * d) / (b * c)
    se = math.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
    return orr, math.exp(math.log(orr) - 1.96 * se), math.exp(math.log(orr) + 1.96 * se)


def chi2_1df_sf(x):
    return math.erfc(math.sqrt(max(x, 0) / 2))


def cmh(strata):
    """strata: list of (a,b,c,d). MH OR (+RGB 95% CI), CMH chi2 with/without continuity, exact conditional p."""
    num = den = 0.0
    sa = se = sv = 0.0
    PR = PS = QS = 0.0  # Robins-Breslow-Greenland
    conv = {0: 1.0}
    obs = 0
    for a, b, c, d in strata:
        n = a + b + c + d
        n1, n2, m1, m2 = a + b, c + d, a + c, b + d
        if n < 2 or m1 == 0 or m2 == 0 or n1 == 0 or n2 == 0:
            continue  # uninformative stratum
        r, s = a * d / n, b * c / n
        num += r; den += s
        p, q = (a + d) / n, (b + c) / n
        PR += p * r; PS += p * s + q * r; QS += q * s
        sa += a
        se += n1 * m1 / n
        sv += n1 * n2 * m1 * m2 / (n * n * (n - 1))
        pmf = hyper_pmf(n1, n2, m1)
        new = collections.defaultdict(float)
        for t, pt in conv.items():
            for k, pk in pmf.items():
                new[t + k] += pt * pk
        conv = dict(new)
        obs += a
    if den == 0 or sv == 0:
        return None
    mh = num / den
    var_log = PR / (2 * num * num) + PS / (2 * num * den) + QS / (2 * den * den)
    lo, hi = math.exp(math.log(mh) - 1.96 * math.sqrt(var_log)), math.exp(math.log(mh) + 1.96 * math.sqrt(var_log))
    x_cc = (abs(sa - se) - 0.5) ** 2 / sv
    x_nc = (sa - se) ** 2 / sv
    return dict(mh_or=mh, mh_lo=lo, mh_hi=hi, obs=sa, exp=se, var=sv,
                chi2_cc=x_cc, p_cc=chi2_1df_sf(x_cc), chi2=x_nc, p=chi2_1df_sf(x_nc),
                p_exact=two_sided(conv, obs), p_exact_one=sum(p for k, p in conv.items() if k >= obs))


# ---------------------------------------------------------------- analysis
def tabulate(rows, first_of):
    """Per-PR [first_miss, first_solved, second_miss, second_solved]."""
    t = collections.OrderedDict()
    for r in rows:
        pr = r["_pr"]
        x = t.setdefault(pr, [0, 0, 0, 0])
        first = r["_side"] == first_of(r)
        miss = not r.get("success")
        x[(0 if first else 2) + (0 if miss else 1)] += 1
    return t


def summarize(label, table):
    tot = [sum(v[i] for v in table.values()) for i in range(4)]
    a, b, c, d = tot
    p2, p1 = fisher(a, b, c, d)
    orr = odds_ratio(a, b, c, d)
    st = cmh(list(table.values()))
    return dict(label=label, n_prs=len(table), a=a, b=b, c=c, d=d, fisher_p=p2, fisher_p_one=p1,
                or_=orr, cmh=st)


def fmt_res(s):
    a, b, c, d = s["a"], s["b"], s["c"], s["d"]
    o, lo, hi = s["or_"]
    line = (f"{s['label']}: PRs={s['n_prs']} first {a}/{a+b} miss ({a/(a+b):.1%}) vs second {c}/{c+d} "
            f"({c/(c+d):.1%}); Fisher two-sided p={s['fisher_p']:.3g} (one-sided first>second p={s['fisher_p_one']:.3g}); "
            f"OR={o:.2f} [{lo:.2f}, {hi:.2f}]")
    m = s["cmh"]
    if m:
        line += (f"; MH OR={m['mh_or']:.2f} [{m['mh_lo']:.2f}, {m['mh_hi']:.2f}], CMH p={m['p_cc']:.3g} (cc) / "
                 f"{m['p']:.3g} (no cc), exact conditional p={m['p_exact']:.3g}")
    return line


def main():
    if not os.path.isdir(R):
        sys.exit("run from repo root")
    notes = []
    excluded = collections.Counter()
    excluded_by_pr = collections.Counter()
    canon_rows = []
    checks = collections.Counter()
    for d, prs in CANON.items():
        for pr in prs:
            rows = load(d, pr)
            assert rows, (d, pr)
            fs_expected = first_side_for(SEED, pr, SIDES)
            keys = collections.Counter((r.get("task"), r["_side"], r.get("trial")) for r in rows)
            dup = [k for k, n in keys.items() if n > 1]
            if dup:
                notes.append(f"{pr}: duplicate (task, side, trial) keys {dup}")
            blocks = collections.defaultdict(dict)
            for r in rows:
                if r.get("first_side") != fs_expected:
                    checks["first_side_mismatch"] += 1
                if r.get("run_seed") != SEED:
                    checks["run_seed_mismatch"] += 1
                if r.get("upstream_model") not in ("claude-sonnet-5-5", None):
                    checks["non_sonnet_upstream"] += 1
                if r.get("upstream_model") is None and r.get("failure_class") not in EX:
                    checks["judged_without_upstream_model"] += 1
                blocks[(r.get("task"), r.get("trial"))][r["_side"]] = r
            for (task, trial), bs in blocks.items():
                if len(bs) == 2:
                    f, s = bs[fs_expected], bs[[x for x in SIDES if x != fs_expected][0]]
                    checks["blocks_both_sides"] += 1
                    if f.get("schedule_index", 0) < s.get("schedule_index", 0):
                        checks["blocks_first_scheduled_first"] += 1
                    if (f.get("started_at") or 0) <= (s.get("started_at") or 0):
                        checks["blocks_first_started_first"] += 1
            for r in rows:
                fc = r.get("failure_class")
                if fc in EX:
                    reason = (r.get("failure_reason") or r.get("error") or "")
                    reason = str(reason).strip().splitlines()[-1][:90] if str(reason).strip() else "-"
                    excluded[(fc, reason)] += 1
                    excluded_by_pr[(pr, r["_side"] == fs_expected)] += 1
                else:
                    canon_rows.append(r)

    fs = lambda r: first_side_for(SEED, r["_pr"], SIDES)
    prim = tabulate(canon_rows, fs)
    res_prim = summarize("PRIMARY (canonical seeded cells, all PRs)", prim)

    # per-PR pass-rate Fisher (side == arm within a PR, so this is the PR's own pass-rate contrast)
    per_pr = []
    for pr, (a, b, c, d) in prim.items():
        p2, _ = fisher(a, b, c, d)
        per_pr.append((pr, fs({"_pr": pr}), a, b, c, d, p2))
    flagged = [pr for pr, _, a, b, c, d, p in per_pr if p < 0.05]

    sens = []
    sens.append(summarize(f"S1 drop PRs with per-PR pass-rate p<0.05 ({', '.join(flagged) or 'none'})",
                          collections.OrderedDict((k, v) for k, v in prim.items() if k not in flagged)))
    hang_rows = [r for r in canon_rows if r.get("success") or r.get("failure_class") in ("hang", "timeout")]
    wa_rows = [r for r in canon_rows if r.get("success") or r.get("failure_class") == "wrong_answer"]
    sens.append(summarize("S2 hangs+timeouts only (wrong answers dropped)", tabulate(hang_rows, fs)))
    sens.append(summarize("S3 wrong answers only (hangs/timeouts dropped)", tabulate(wa_rows, fs)))
    sens.append(summarize(f"S3b wrong answers only, without {', '.join(flagged) or '-'}",
                          tabulate([r for r in wa_rows if r["_pr"] not in flagged], fs)))
    # superseded seeded runs added as extra strata
    extra = []
    for d, prs in SUPERSEDED_SEEDED.items():
        for pr in prs:
            for r in load(d, pr):
                if r.get("failure_class") not in EX:
                    r["_pr"] = f"{pr}@{d.replace('step3-sonnet-1016', 'main') or 'main'}"
                    r["_fs"] = first_side_for(SEED, pr, SIDES)
                    extra.append(r)
    t4 = tabulate(canon_rows + extra, lambda r: r.get("_fs") or fs(r))
    sens.append(summarize(f"S4 + superseded seeded runs ({len(extra)} judged cells)", t4))
    # old fixed-order interleave runs (without always first) as extra strata
    old = []
    for (d, pr), why in NOT_SEEDED.items():
        if "OLD ORDER" in why:
            for r in load(d, pr):
                if r.get("failure_class") not in EX:
                    r["_pr"] = f"{pr}@{'oldorder' if 'partial' in d else 'old'}"
                    r["_fs"] = "without"
                    old.append(r)
    t5 = tabulate(canon_rows + old, lambda r: r.get("_fs") or fs(r))
    sens.append(summarize(f"S5 + OLD-ORDER interleave runs, first=without ({len(old)} judged cells)", t5))
    # contrast: with vs without (the PR effect) pooled, for context
    tw = tabulate(canon_rows, lambda r: "with")
    res_with = summarize("CONTEXT with-side (rows) vs without-side, same cells", tw)

    # ---- write CSVs
    with open(os.path.join(OUT, "table_2x2.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["position", "miss", "solved", "total", "miss_rate"])
        a, b, c, d = res_prim["a"], res_prim["b"], res_prim["c"], res_prim["d"]
        w.writerow(["first", a, b, a + b, f"{a/(a+b):.4f}"])
        w.writerow(["second", c, d, c + d, f"{c/(c+d):.4f}"])
        w.writerow(["total", a + c, b + d, a + b + c + d, f"{(a+c)/(a+b+c+d):.4f}"])
    miss_cls = collections.defaultdict(collections.Counter)
    for r in canon_rows:
        if not r.get("success"):
            miss_cls[r["_pr"]][(r["_side"] == fs(r), r.get("failure_class"))] += 1
    with open(os.path.join(OUT, "per_pr.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["pr", "data_dir", "first_side", "first_miss", "first_solved", "second_miss", "second_solved",
                    "first_wrong", "first_hang", "first_timeout", "second_wrong", "second_hang", "second_timeout",
                    "excluded_first", "excluded_second", "pr_passrate_fisher_p"])
        dir_of = {pr: d for d, prs in CANON.items() for pr in prs}
        for pr, fside, a, b, c, d, p in per_pr:
            mc = miss_cls[pr]
            w.writerow([pr, dir_of[pr], fside, a, b, c, d,
                        mc[(True, "wrong_answer")], mc[(True, "hang")], mc[(True, "timeout")],
                        mc[(False, "wrong_answer")], mc[(False, "hang")], mc[(False, "timeout")],
                        excluded_by_pr[(pr, True)], excluded_by_pr[(pr, False)], f"{p:.4g}"])
    with open(os.path.join(OUT, "excluded.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["failure_class", "reason", "cells"])
        for (fc, reason), n in excluded.most_common():
            w.writerow([fc, reason, n])
    # approximate power of the pooled two-sided test (normal approx, alpha .05)
    n1, n2 = res_prim["a"] + res_prim["b"], res_prim["c"] + res_prim["d"]
    p0 = (res_prim["a"] + res_prim["c"]) / (n1 + n2)
    power = {}
    for orv in (1.5, 2.0, 2.5, 3.0):
        p1 = orv * p0 / (1 - p0 + orv * p0)
        pbar = (p1 + p0) / 2
        se0 = math.sqrt(pbar * (1 - pbar) * (1 / n1 + 1 / n2))
        se1 = math.sqrt(p1 * (1 - p1) / n1 + p0 * (1 - p0) / n2)
        z = (abs(p1 - p0) - 1.96 * se0) / se1
        power[orv] = 0.5 * math.erfc(-z / math.sqrt(2))
    print("power (first-side OR -> power):", {k: round(v, 2) for k, v in power.items()}, "base miss", round(p0, 4))
    summary = dict(primary=res_prim, power=power, sensitivities=sens, context_with_vs_without=res_with,
                   checks=dict(checks), excluded_total=sum(excluded.values()), notes=notes,
                   judged_cells=len(canon_rows), per_pr=per_pr)
    with open(os.path.join(OUT, "results.json"), "w") as f:
        json.dump(summary, f, indent=1, default=str)
    print(fmt_res(res_prim))
    for s in sens:
        print(fmt_res(s))
    print(fmt_res(res_with))
    print("checks", dict(checks))
    print("excluded", sum(excluded.values()), excluded.most_common())
    print("excluded first/second:", sum(n for (pr, f), n in excluded_by_pr.items() if f),
          sum(n for (pr, f), n in excluded_by_pr.items() if not f))
    print("notes", notes)
    for row in per_pr:
        print(row)


if __name__ == "__main__":
    main()
