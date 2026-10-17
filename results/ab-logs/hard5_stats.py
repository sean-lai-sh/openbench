#!/usr/bin/env python3
"""Helpers for hard5 (5-trial) A/B driver on cleared-noise PRs."""
from __future__ import annotations

import glob
import json
import os
import statistics as st
import sys

sys.path.insert(0, "/workspace/openbench-ab")
from thesis.ab.summarize import row_cost, toolchain_from, sdk_versions_differ

PRS = [26821, 13331, 23771, 2334, 3115]
# First-pass PRs where ±12/±19/±11 A/A noise floor applies.
FIRST_PASS = {26821, 13331, 23771}
# Tiny-cell set-aside clears — do NOT treat 3-trial noise floor as confirmed.
TINY_SETASIDE = {2334, 3115}
NOISE = {"wall": 12.0, "tok": 19.0, "cost": 11.0}
# Token vs cost Δ% disagreement threshold (absolute percentage points).
TOK_COST_DISAGREE_PP = 5.0

PROGRESS_MD = "results/ab-logs/hard5-progress.md"
REPORT_MD = "results/ab-logs/hard5-report.md"
LATEST_TXT = "results/ab-logs/hard5-latest.txt"
PRIOR_FILE = "results/ab-logs/hard5-prior.txt"
LIVE0_FILE = "results/ab-logs/hard5-live0.txt"


def rows(pr, side):
    out = []
    for p in glob.glob(f"results/ab/{pr}/cells/{side}/*/*.json"):
        try:
            out.append(json.load(open(p)))
        except Exception:
            pass
    return out


def live_total():
    t = 0.0
    for p in glob.glob("results/ab/*/cells/*/*/*.json"):
        try:
            c = row_cost(json.load(open(p)))
        except Exception:
            c = None
        t += c or 0
    return t


def prior():
    if os.path.exists(PRIOR_FILE):
        return float(open(PRIOR_FILE).read().strip())
    return live_total()


def live0():
    if os.path.exists(LIVE0_FILE):
        return float(open(LIVE0_FILE).read().strip())
    return live_total()


def cumulative():
    """PRIOR (pre-wipe, includes 3-trial for these PRs) + new hard5 spend only."""
    return prior() + max(0.0, live_total() - live0())


def total():
    """Alias used by driver for spend checks — true cumulative est."""
    return cumulative()


def load_toolchain(pr, side):
    path = f"results/ab/{pr}/{side}.toolchain.json"
    if os.path.exists(path):
        try:
            return toolchain_from(json.load(open(path)))
        except Exception:
            pass
    for r in rows(pr, side):
        found = toolchain_from(r.get("toolchain") if isinstance(r, dict) else None)
        if found:
            return found
    return {}


def incompatible(pr, side):
    for kind in ("incompatible", "infra"):
        path = f"results/ab/{pr}/{side}.{kind}.json"
        if os.path.exists(path):
            try:
                return json.load(open(path))
            except Exception:
                return {"status": kind, "reason": "unreadable sidecar"}
    return None


def side_stats(pr, side):
    inc = incompatible(pr, side)
    if inc:
        return {
            "incompatible": True,
            "status": inc.get("status") or "incompatible",
            "reason": (inc.get("reason") or "")[:200],
            "toolchain": load_toolchain(pr, side),
        }
    r = rows(pr, side)
    if not r:
        return {"incompatible": False, "empty": True, "toolchain": load_toolchain(pr, side)}
    f = lambda k: [x[k] for x in r if x.get(k) is not None]
    tok = [
        (x.get("tokens_input_uncached") or 0)
        + (x.get("tokens_output") or 0)
        + (x.get("tokens_cache_read") or 0)
        + (x.get("tokens_cache_write") or 0)
        for x in r
        if x.get("tokens_output") is not None
    ]
    costs = [row_cost(x) for x in r]
    mc = [c for c in costs if c is not None]
    # success/fail split for $/cell notes (esp. 2334)
    ok = [x for x in r if x.get("success")]
    fail = [x for x in r if not x.get("success")]
    fail_costs = [row_cost(x) for x in fail]
    fail_mc = [c for c in fail_costs if c is not None]
    return {
        "incompatible": False,
        "empty": False,
        "n": len(r),
        "n_ok": len(ok),
        "n_fail": len(fail),
        "pass": sum(1 for x in r if x.get("success")) / len(r),
        "wall": st.mean(f("wall_time_s")) if f("wall_time_s") else None,
        "turns": st.mean(f("turns")) if f("turns") else None,
        "tok": st.mean(tok) if tok else None,
        "cost": st.mean(mc) if mc else None,
        "sum": sum(mc),
        "unm": len(costs) - len(mc),
        "fail_cost_mean": st.mean(fail_mc) if fail_mc else None,
        "fail_n_costed": len(fail_mc),
        "toolchain": load_toolchain(pr, side),
        "by_task": _by_task(r),
    }


def _cell_tok(x):
    if x.get("tokens_output") is None:
        return None
    return (
        (x.get("tokens_input_uncached") or 0)
        + (x.get("tokens_output") or 0)
        + (x.get("tokens_cache_read") or 0)
        + (x.get("tokens_cache_write") or 0)
    )


def _by_task(r):
    buckets = {}
    for x in r:
        t = str(x.get("task") or "?")
        buckets.setdefault(t, []).append(x)
    out = {}
    for t, xs in buckets.items():
        toks = [v for v in (_cell_tok(x) for x in xs) if v is not None]
        costs = [c for c in (row_cost(x) for x in xs) if c is not None]
        out[t] = {
            "n": len(xs),
            "pass": sum(1 for x in xs if x.get("success")) / len(xs),
            "tok": st.mean(toks) if toks else None,
            "cost": st.mean(costs) if costs else None,
            "n_fail": sum(1 for x in xs if not x.get("success")),
        }
    return out


def fmt_tool(t):
    if not t:
        return "unknown"
    parts = []
    if t.get("bun"):
        parts.append(f"bun={t['bun']}")
    if t.get("ai"):
        parts.append(f"ai={t['ai']}")
    if t.get("anthropic"):
        parts.append(f"anthropic={t['anthropic']}")
    return ",".join(parts) if parts else "unknown"


def pct(a, b):
    if a is None or b is None or a == 0:
        return None
    return (b - a) / a * 100


def _f(v, spec):
    if v is None:
        return "n/a"
    try:
        return format(v, spec)
    except Exception:
        return "n/a"


def clears_noise(dw, dt, dc):
    if dw is None or dt is None or dc is None:
        return False
    return abs(dw) > NOISE["wall"] or abs(dt) > NOISE["tok"] or abs(dc) > NOISE["cost"]


def tok_cost_disagree(dt, dc):
    """True if |token Δ% − cost Δ%| exceeds threshold."""
    if dt is None or dc is None:
        return False
    return abs(dt - dc) > TOK_COST_DISAGREE_PP


def disagree_notes(pr, b, a):
    notes = []
    dt = pct(b.get("tok"), a.get("tok"))
    dc = pct(b.get("cost"), a.get("cost"))
    if tok_cost_disagree(dt, dc):
        notes.append(
            f"PR-aggregate token Δ% ({dt:+.1f}%) vs cost Δ% ({dc:+.1f}%) disagree by "
            f"{abs(dt-dc):.1f}pp (>{TOK_COST_DISAGREE_PP:.0f}pp) — likely metering/counting, not harness"
        )
    bt = b.get("by_task") or {}
    at = a.get("by_task") or {}
    for task in sorted(set(bt) | set(at)):
        sb, sa = bt.get(task), at.get(task)
        if not sb or not sa:
            continue
        tdt = pct(sb.get("tok"), sa.get("tok"))
        tdc = pct(sb.get("cost"), sa.get("cost"))
        if tok_cost_disagree(tdt, tdc):
            notes.append(
                f"task {task}: tok Δ%={tdt:+.1f}% cost Δ%={tdc:+.1f}% "
                f"(disagree {abs(tdt-tdc):.1f}pp); "
                f"fail n {sb.get('n_fail')}→{sa.get('n_fail')}"
            )
    if int(pr) in TINY_SETASIDE or (b.get("n_fail") or 0) or (a.get("n_fail") or 0):
        if tok_cost_disagree(dt, dc) or int(pr) == 2334:
            notes.append(
                f"$/cell fail mix: without n_fail={b.get('n_fail')} "
                f"fail_cost_mean=${_f(b.get('fail_cost_mean'), '.4f')} "
                f"({b.get('fail_n_costed')} costed); "
                f"with n_fail={a.get('n_fail')} "
                f"fail_cost_mean=${_f(a.get('fail_cost_mean'), '.4f')} "
                f"({a.get('fail_n_costed')} costed). "
                f"Check whether $/cell includes failed/retry cells differently after vs before."
            )
    return notes


def noise_label(pr, dw, dt, dc):
    pid = int(pr)
    if pid in TINY_SETASIDE:
        # Still compute vs band for reference, but annotate that 3-trial tiny-cell clear is not confirmed.
        clear = clears_noise(dw, dt, dc)
        band = "CLEAR*" if clear else "within*"
        return band + " (tiny-cell cohort; first-pass A/A ±12/±19/±11 not applied as confirmed floor)"
    return "CLEAR" if clears_noise(dw, dt, dc) else "within"


def one_line(pr):
    b, a = side_stats(pr, "without"), side_stats(pr, "with")
    sdk_changed = sdk_versions_differ(b.get("toolchain") or {}, a.get("toolchain") or {})
    sdk_note = (
        f" SDK without[{fmt_tool(b.get('toolchain'))}] with[{fmt_tool(a.get('toolchain'))}]"
        + (" SDK_CHANGED" if sdk_changed else "")
    )
    bits = []
    for label, s in (("without", b), ("with", a)):
        if s.get("incompatible"):
            bits.append(f"{label}: {s.get('status')} ({s.get('reason')})")
        elif s.get("empty"):
            bits.append(f"{label}: no cells")
        else:
            tok_k = (s["tok"] / 1e3) if s.get("tok") is not None else None
            bits.append(
                f"{label}: n={s['n']} pass={_f(s.get('pass'), '.3f')} wall={_f(s.get('wall'), '.1f')}s "
                f"turns={_f(s.get('turns'), '.1f')} tok={_f(tok_k, '.0f')}k cost=${_f(s.get('cost'), '.3f')}"
                + (f" UNMETERED={s['unm']}" if s.get("unm") else "")
            )
    if (
        not b.get("incompatible")
        and not a.get("incompatible")
        and not b.get("empty")
        and not a.get("empty")
    ):
        dw, dt, dc = pct(b["wall"], a["wall"]), pct(b["tok"], a["tok"]), pct(b["cost"], a["cost"])
        bt = (b["tok"] / 1e3) if b.get("tok") is not None else None
        at = (a["tok"] / 1e3) if a.get("tok") is not None else None
        dw_s = f"{dw:+.1f}%" if dw is not None else "n/a"
        dt_s = f"{dt:+.1f}%" if dt is not None else "n/a"
        dc_s = f"{dc:+.1f}%" if dc is not None else "n/a"
        summary = (
            f"pass {_f(b.get('pass'), '.3f')}→{_f(a.get('pass'), '.3f')}; "
            f"wall {_f(b.get('wall'), '.1f')}→{_f(a.get('wall'), '.1f')}s ({dw_s}); "
            f"turns {_f(b.get('turns'), '.1f')}→{_f(a.get('turns'), '.1f')}; "
            f"tok {_f(bt, '.0f')}k→{_f(at, '.0f')}k ({dt_s}); "
            f"cost ${_f(b.get('cost'), '.3f')}→${_f(a.get('cost'), '.3f')} ({dc_s}); "
            f"PR ${(b.get('sum') or 0)+(a.get('sum') or 0):.2f}"
        )
        label = noise_label(pr, dw, dt, dc)
        line = f"PR {pr}: {summary}; noise_floor={label};{sdk_note}"
        for n in disagree_notes(pr, b, a):
            line += f" | FLAG: {n}"
        return line
    return f"PR {pr}: {' | '.join(bits)};{sdk_note}"


def progress_block(pr, status):
    lines = ["\n## PR %s (%s)\n" % (pr, status), "- %s\n" % one_line(pr)]
    b, a = side_stats(pr, "without"), side_stats(pr, "with")
    for side, s in (("without", b), ("with", a)):
        if s.get("incompatible"):
            lines.append("- %s: %s — %s\n" % (side, s.get("status"), s.get("reason")))
        elif s.get("empty"):
            lines.append("- %s: no cells\n" % side)
        else:
            lines.append(
                "- %s: n=%s pass=%s wall=%ss turns=%s tok/cell=%s cost/cell=$%s "
                "(n_ok=%s n_fail=%s)\n"
                % (
                    side,
                    s["n"],
                    _f(s.get("pass"), ".3f"),
                    _f(s.get("wall"), ".1f"),
                    _f(s.get("turns"), ".1f"),
                    _f(s.get("tok"), ".0f"),
                    _f(s.get("cost"), ".3f"),
                    s.get("n_ok"),
                    s.get("n_fail"),
                )
            )
        lines.append("- %s toolchain: %s\n" % (side, fmt_tool(s.get("toolchain"))))
    if (
        not b.get("incompatible")
        and not a.get("incompatible")
        and not b.get("empty")
        and not a.get("empty")
    ):
        dt = pct(b.get("tok"), a.get("tok"))
        dc = pct(b.get("cost"), a.get("cost"))
        lines.append(
            "- tok vs cost: tok %s→%s (Δ %s); cost $%s→$%s (Δ %s)\n"
            % (
                _f(b.get("tok"), ".0f"),
                _f(a.get("tok"), ".0f"),
                f"{dt:+.1f}%" if dt is not None else "n/a",
                _f(b.get("cost"), ".3f"),
                _f(a.get("cost"), ".3f"),
                f"{dc:+.1f}%" if dc is not None else "n/a",
            )
        )
        for n in disagree_notes(pr, b, a):
            lines.append("- **FLAG:** %s\n" % n)
        if int(pr) in TINY_SETASIDE:
            lines.append(
                "- note: set-aside 3-trial was tiny (~5s/16k, pass 0→0); "
                "do not treat prior CLEAR as confirmed under first-pass A/A noise floor.\n"
            )
    lines.append(
        "- cumulative spend (all phases, est.): $%.2f "
        "(prior=$%.2f hard5_new=$%.2f)\n"
        % (cumulative(), prior(), max(0.0, live_total() - live0()))
    )
    return "".join(lines)


def table_row(pr):
    b, a = side_stats(pr, "without"), side_stats(pr, "with")
    sdk_changed = sdk_versions_differ(b.get("toolchain") or {}, a.get("toolchain") or {})
    flag = "yes" if sdk_changed else ""
    if b.get("incompatible") or a.get("incompatible") or b.get("empty") or a.get("empty"):
        reasons = []
        for label, s in (("without", b), ("with", a)):
            if s.get("incompatible"):
                reasons.append("%s: %s" % (label, s.get("reason")))
            elif s.get("empty"):
                reasons.append("%s: no cells" % label)
        return "| %s | — | — | — | — | — | — | — | %s | %s |" % (pr, flag, " ; ".join(reasons))
    dw, dt, dc = pct(b["wall"], a["wall"]), pct(b["tok"], a["tok"]), pct(b["cost"], a["cost"])
    label = noise_label(pr, dw, dt, dc)
    if tok_cost_disagree(dt, dc):
        label += "; tok/cost DISAGREE"
    dw_s = ("%+.1f%%" % dw) if dw is not None else "n/a"
    dt_s = ("%+.1f%%" % dt) if dt is not None else "n/a"
    dc_s = ("%+.1f%%" % dc) if dc is not None else "n/a"
    bt = (b["tok"] / 1e3) if b.get("tok") is not None else None
    at = (a["tok"] / 1e3) if a.get("tok") is not None else None
    return (
        "| %s | %s/%s | %s→%s | %s→%s (%s) | %s→%s | %sk→%sk (%s) | %s→%s (%s) | %.2f | %s | %s |"
        % (
            pr,
            b["n"],
            a["n"],
            _f(b.get("pass"), ".3f"),
            _f(a.get("pass"), ".3f"),
            _f(b.get("wall"), ".1f"),
            _f(a.get("wall"), ".1f"),
            dw_s,
            _f(b.get("turns"), ".1f"),
            _f(a.get("turns"), ".1f"),
            _f(bt, ".0f"),
            _f(at, ".0f"),
            dt_s,
            _f(b.get("cost"), ".3f"),
            _f(a.get("cost"), ".3f"),
            dc_s,
            (b.get("sum") or 0) + (a.get("sum") or 0),
            flag,
            label,
        )
    )


def write_report(path=None):
    if path is None:
        path = REPORT_MD
    spend = cumulative()
    hard5_new = max(0.0, live_total() - live0())
    lines = [
        "# Harder-task 5-trial A/B report (auto-generated)\n",
        "\nWorktree /workspace/openbench-ab @ e04d456 (PR #6). "
        "Driver: results/ab-logs/hard5.sh. "
        "Command: `python3 -m thesis.ab.run_ab thesis/ab/fixtures/opencode-harness-prs.csv "
        "--pr <PR> --trials 5 --jobs 8 --out results/ab "
        "--cache /workspace/openbench-ab/results/opencode-src` (all 8 core tasks).\n",
        "\nPRs: first-pass clears 26821, 13331, 23771; set-aside tiny-cell cohort 2334, 3115 "
        "(3-trial CLEAR not confirmed under first-pass A/A floor).\n",
        "\nCumulative est. spend (all phases): $%.2f "
        "(prior pre-hard5 $%.2f + hard5 new $%.2f). Soft pause ~$700.\n"
        % (spend, prior(), hard5_new),
        "\nNoise floor (first-pass A/A+controls): ±%.0f%% wall, ±%.0f%% tokens, ±%.0f%% cost. "
        "CLEAR = outside band for first-pass PRs. "
        "Tiny-cell set-aside PRs marked with * — band shown for reference only.\n"
        % (NOISE["wall"], NOISE["tok"], NOISE["cost"]),
        "\nToken vs cost: report both Δ%% side by side. "
        "FLAG when |tok Δ%% − cost Δ%%| > %.0fpp (metering/counting suspicion).\n"
        % TOK_COST_DISAGREE_PP,
        "\n| PR | n (b/a) | Pass b→a | Wall s b→a (Δ%) | Turns b→a | "
        "Tok/cell b→a (Δ%) | $/cell b→a (Δ%) | PR $ | SDK changed | vs noise |\n",
        "|---|---|---|---|---|---|---|---|---|---|\n",
    ]
    clears = []
    for pr in PRS:
        lines.append(table_row(pr) + "\n")
        b, a = side_stats(pr, "without"), side_stats(pr, "with")
        if (
            not b.get("incompatible")
            and not a.get("incompatible")
            and not b.get("empty")
            and not a.get("empty")
        ):
            dw, dt, dc = pct(b["wall"], a["wall"]), pct(b["tok"], a["tok"]), pct(b["cost"], a["cost"])
            if int(pr) in FIRST_PASS and clears_noise(dw, dt, dc):
                clears.append(str(pr))
    lines.append("\n## Clears noise floor (first-pass cohort only)\n")
    lines.append((", ".join(clears) if clears else "(none)") + "\n")
    lines.append("\n## Token vs cost disagreement flags\n\n")
    any_flag = False
    for pr in PRS:
        b, a = side_stats(pr, "without"), side_stats(pr, "with")
        if b.get("incompatible") or a.get("incompatible") or b.get("empty") or a.get("empty"):
            continue
        notes = disagree_notes(pr, b, a)
        if notes:
            any_flag = True
            lines.append(f"### PR {pr}\n")
            for n in notes:
                lines.append(f"- {n}\n")
    if not any_flag:
        lines.append("(none)\n")
    lines.append("\n## Quarantine\n\n")
    lines.append(
        "Pre-hard5 3-trial cells copied to `results/ab-quarantine/pre-hard5-<pr>/` "
        "before wipe+5-trial rerun.\n"
    )
    lines.append(
        "\nSpend: cumulative est. **$%.2f** (prior $%.2f; hard5 phase +$%.2f).\n"
        % (spend, prior(), hard5_new)
    )
    with open(path, "w") as fh:
        fh.write("".join(lines))
    return path


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "total"
    if cmd == "total":
        print(f"{total():.2f}")
    elif cmd == "live":
        print(f"{live_total():.2f}")
    elif cmd == "cumulative":
        print(f"{cumulative():.2f}")
    elif cmd == "progress":
        pr = argv[2]
        status = argv[3] if len(argv) > 3 else "done"
        block = progress_block(pr, status)
        with open(PROGRESS_MD, "a") as fh:
            fh.write(block)
        print(block)
    elif cmd == "report":
        p = write_report()
        print(p)
    elif cmd == "oneline":
        print(one_line(argv[2]))
    else:
        print("usage: hard5_stats.py total|live|cumulative|progress PR [status]|report|oneline PR", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
