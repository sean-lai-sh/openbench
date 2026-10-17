#!/usr/bin/env python3
"""Helpers for the set-aside 17 A/B driver (post PR #5 / aecd3fa)."""
from __future__ import annotations

from pathlib import Path

import json
import glob
import os
import statistics as st
import sys

sys.path.insert(0, "/workspace/openbench-ab")
from thesis.ab.summarize import row_cost, toolchain_from, sdk_versions_differ, SDK_CHANGED

PRS = [
    623, 913, 984, 1248, 2334, 2367, 3052, 3115, 3369, 3418,
    4204, 4838, 5066, 5131, 5140, 5527, 6524,
]
NOISE = {"wall": 12.0, "tok": 19.0, "cost": 11.0}  # ±% from A/A+controls
import os as _os
_ROUND = _os.environ.get("SETASIDE_ROUND", "1")
PROGRESS_MD = "results/ab-logs/setaside2-progress.md" if _ROUND == "2" else "results/ab-logs/setaside-progress.md"
REPORT_MD = "results/ab-logs/setaside2-report.md" if _ROUND == "2" else "results/ab-logs/setaside-report.md"
LATEST_TXT = "results/ab-logs/setaside2-latest.txt" if _ROUND == "2" else "results/ab-logs/setaside-latest.txt"


def rows(pr, side):
    out = []
    for p in glob.glob(f"results/ab/{pr}/cells/{side}/*/*.json"):
        try:
            out.append(json.load(open(p)))
        except Exception:
            pass
    return out


def total():
    t = 0.0
    for p in glob.glob("results/ab/*/cells/*/*/*.json"):
        try:
            c = row_cost(json.load(open(p)))
        except Exception:
            c = None
        t += c or 0
    return t


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
        return {"incompatible": True, "status": inc.get("status") or "incompatible",
                "reason": (inc.get("reason") or "")[:200], "toolchain": load_toolchain(pr, side)}
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
    return {
        "incompatible": False,
        "empty": False,
        "n": len(r),
        "pass": sum(1 for x in r if x.get("success")) / len(r),
        "wall": st.mean(f("wall_time_s")) if f("wall_time_s") else None,
        "turns": st.mean(f("turns")) if f("turns") else None,
        "tok": st.mean(tok) if tok else None,
        "cost": st.mean(mc) if mc else None,
        "sum": sum(mc),
        "unm": len(costs) - len(mc),
        "toolchain": load_toolchain(pr, side),
    }


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


def one_line(pr):
    b, a = side_stats(pr, "without"), side_stats(pr, "with")
    sdk_changed = sdk_versions_differ(b.get("toolchain") or {}, a.get("toolchain") or {})
    sdk_note = (
        f" SDK without[{fmt_tool(b.get('toolchain'))}] with[{fmt_tool(a.get('toolchain'))}]"
        + (" SDK changed" if sdk_changed else "")
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
        clear = clears_noise(dw, dt, dc)
        return f"PR {pr}: {summary}; noise_floor={'CLEAR' if clear else 'within'};{sdk_note}"
    return f"PR {pr}: {' | '.join(bits)};{sdk_note}"


def clears_noise(dw, dt, dc):
    """True if any metric exceeds the A/A+controls noise band."""
    if dw is None or dt is None or dc is None:
        return False
    return abs(dw) > NOISE["wall"] or abs(dt) > NOISE["tok"] or abs(dc) > NOISE["cost"]



def progress_block(pr, status):
    lines = ["\n## PR %s (%s)\n" % (pr, status), "- %s\n" % one_line(pr)]
    for side in ("without", "with"):
        s = side_stats(pr, side)
        if s.get("incompatible"):
            lines.append("- %s: %s — %s\n" % (side, s.get("status"), s.get("reason")))
        elif s.get("empty"):
            lines.append("- %s: no cells\n" % side)
        else:
            lines.append(
                "- %s: n=%s pass=%s wall=%ss turns=%s tok/cell=%s cost/cell=$%s\n"
                % (
                    side,
                    s["n"],
                    _f(s.get("pass"), ".3f"),
                    _f(s.get("wall"), ".1f"),
                    _f(s.get("turns"), ".1f"),
                    _f(s.get("tok"), ".0f"),
                    _f(s.get("cost"), ".3f"),
                )
            )
        lines.append("- %s toolchain: %s\n" % (side, fmt_tool(s.get("toolchain"))))
    lines.append("- cumulative spend (all phases, est.): $%.2f\n" % total())
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
    clear = "CLEAR" if clears_noise(dw, dt, dc) else "within"
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
            clear,
        )
    )


def write_report(path=None):
    if path is None:
        path = REPORT_MD
    spend = total()
    driver = "setaside2.sh" if _ROUND == "2" else "setaside.sh"
    lines = [
        "# Set-aside 17 report (auto-generated)\n",
        "\nWorktree /workspace/openbench-ab @ e04d456 (PR #6) [round %s]. "
        "Driver: results/ab-logs/%s. "
        "Command: `python3 -m thesis.ab.run_ab thesis/ab/fixtures/opencode-harness-prs.csv "
        "--pr <PR> --trials 3 --jobs 8 --out results/ab "
        "--cache /workspace/openbench-ab/results/opencode-src`.\n" % (_ROUND, driver),
        "\nCumulative est. spend (all phases): $%.2f "
        "(baseline before set-aside ≈ $414; phase soft cap ~$400 / overall ~$800–1000).\n" % spend,
        "\nNoise floor (from A/A+controls): ±%.0f%% wall, ±%.0f%% tokens, ±%.0f%% cost. "
        "CLEAR = at least one metric outside the band.\n"
        % (NOISE["wall"], NOISE["tok"], NOISE["cost"]),
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
            if clears_noise(dw, dt, dc):
                clears.append(pr)
    lines.append("\n## Clears noise floor\n")
    lines.append((", ".join(str(x) for x in clears) if clears else "(none yet)") + "\n")
    lines.append("\nConnectionReset note: see per-PR setaside2-<pr>.log CR counts.\n")
    Path(path).write_text("".join(lines))
    # also update latest
    open(LATEST_TXT, "w").write("report written spend=$%.2f\n" % spend)
    return path, spend, clears


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "total":
        print("%.2f" % total())
    elif cmd == "progress":
        pr, status = sys.argv[2], sys.argv[3]
        with open(PROGRESS_MD, "a") as fh:
            fh.write(progress_block(pr, status))
        open(LATEST_TXT, "w").write(one_line(pr) + "\n")
    elif cmd == "report":
        path, spend, clears = write_report()
        print("wrote", path, "spend", spend, "clears", clears)
    elif cmd == "line":
        print(one_line(int(sys.argv[2])))
    else:
        print("usage: setaside_stats.py total|progress PR STATUS|report|line PR", file=sys.stderr)
        sys.exit(2)
