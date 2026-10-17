#!/usr/bin/env python3
"""Re-score existing A/B cells treating rate-limit/timeout truncations as infra.

Read-only over results/ab/<pr>/cells/{without,with}/*/*.json.
No run_ab, no deletes/moves, no paid calls.

Classifier (locked 2026-10-05 by PM): a cell truncated by rate limit
(429 / overloaded / RESOURCE_EXHAUSTED / rate_limit) or timeout
(harness timeout, killed, deadline) is classed infra and excluded from
token/wall/$ means, same as existing ~5s failure_class=infra cells.

Pass-rate is reported both (a) excluding infra and (b) raw success/n.
"""
from __future__ import annotations

import json
import re
import statistics as st
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import sys

sys.path.insert(0, "/workspace/openbench-ab")
from thesis.ab.summarize import row_cost, billable_tokens, RATES, TOKEN_FIELDS  # noqa: F401

ROOT = Path("/workspace/openbench-ab")
CELLS = ROOT / "results" / "ab"

# Hard5 5-trial first-pass rows + ENOENT-set (4204 listed for infra only).
HARD5_PRS = [13331, 23771, 26821]
ENOENT_PRS = [4838, 5066, 5131, 5140, 5527, 6524]
OFF_SHEET = [4204]
ALL_SCORE = HARD5_PRS + ENOENT_PRS

NOISE = {"wall": 12.0, "tok": 19.0, "cost": 11.0}  # first-pass A/A, modern rows
TOK_COST_FLAG_PP = 5.0
ASYM_ABS = 2
ASYM_FRAC = 0.10

# --- truncation → infra classifier -----------------------------------------

# failure_class values that are already infra-like / truncation
FC_INFRA = frozenset({"infra", "rate_limited", "stalled", "timeout"})

RATE_RE = re.compile(
    r"(?:429|overloaded|RESOURCE_EXHAUSTED|rate[_\s-]?limit|ratelimit)",
    re.I,
)
TIMEOUT_RE = re.compile(
    r"(?:timeout\s+after|harness\s+timeout|\bkilled\b|deadline(?:exceeded)?|"
    r"DeadlineExceeded|timed?\s*out)",
    re.I,
)

# ~5s infra deaths (existing pattern on e.g. #4204): short wall + not solved
SHORT_INFRA_WALL_S = 8.0

# Rule 4b (PM-requested 2026-10-05), default OFF: failed cell, wall <8s,
# "Unhandled chunk type" in output, ANY output token count (pre-crash partial
# output). Enable with --rule-4b or RESCORE_RULE_4B=1. Locked rule unchanged.
import os as _os
RULE_4B = _os.environ.get("RESCORE_RULE_4B") == "1" or "--rule-4b" in sys.argv


def _blob(row: dict) -> str:
    parts = [
        row.get("failure_class"),
        row.get("error"),
        row.get("failure_reason"),
        row.get("checker_stderr"),
        row.get("checker_stdout"),
        # output_tail may contain a single 429 mid-transcript; only use it when
        # the cell did not complete successfully (avoid false positives on
        # solved cells that mention "timeout" in code comments).
    ]
    if not row.get("success"):
        parts.append(row.get("output_tail"))
    return " ".join("" if p is None else str(p) for p in parts)


def is_infra(row: dict) -> tuple[bool, str]:
    """Return (is_infra, reason_tag)."""
    fc = row.get("failure_class")
    if fc in FC_INFRA:
        return True, f"failure_class={fc}"

    blob = _blob(row)
    if RATE_RE.search(blob):
        return True, "rate_limit_marker"
    if TIMEOUT_RE.search(blob):
        # Only count timeout markers on unsuccessful / incomplete cells
        if not row.get("success") or row.get("completed") is False:
            return True, "timeout_marker"

    # Existing ~5s infra is already failure_class=infra (caught above).
    # Near-instant exit deaths with tiny output and no formal fc=infra yet
    # (legacy / missing taxonomy) — but never promote incompatible.
    wall = row.get("wall_time_s")
    if (
        fc != "incompatible"
        and isinstance(wall, (int, float))
        and wall < SHORT_INFRA_WALL_S
        and not row.get("success")
        and (row.get("tokens_output") or 0) <= 32
        and (
            str(row.get("error") or "").startswith("exit ")
            or "Unhandled chunk" in str(row.get("output_tail") or "")
        )
    ):
        return True, "short_exit_infra"

    if (
        RULE_4B
        and fc != "incompatible"
        and isinstance(wall, (int, float))
        and wall < SHORT_INFRA_WALL_S
        and not row.get("success")
        and "Unhandled chunk type" in str(row.get("output_tail") or "")
    ):
        return True, "rule_4b_unhandled_chunk"

    return False, ""


def cell_tok(row: dict) -> float | None:
    if row.get("tokens_output") is None:
        return None
    return (
        (row.get("tokens_input_uncached") or 0)
        + (row.get("tokens_output") or 0)
        + (row.get("tokens_cache_read") or 0)
        + (row.get("tokens_cache_write") or 0)
    )


def load_side(pr: int, side: str) -> list[dict]:
    root = CELLS / str(pr) / "cells" / side
    rows = []
    for p in sorted(root.glob("*/*.json")):
        d = json.loads(p.read_text())
        d["_path"] = str(p.relative_to(CELLS / str(pr) / "cells"))
        d["_mtime"] = p.stat().st_mtime
        rows.append(d)
    return rows


def window(row: dict) -> tuple[datetime | None, datetime | None]:
    """Cell time window from ts_iso (start) + wall_time_s; mtime fallback."""
    ts = row.get("ts_iso")
    wall = row.get("wall_time_s")
    start = None
    if isinstance(ts, str) and ts:
        try:
            start = datetime.fromisoformat(ts)
        except ValueError:
            start = None
    if start is None:
        # mtime ≈ end; back out start if wall known
        end = datetime.fromtimestamp(row["_mtime"])
        if isinstance(wall, (int, float)):
            return end - timedelta(seconds=float(wall)), end
        return end, end
    if isinstance(wall, (int, float)):
        return start, start + timedelta(seconds=float(wall))
    return start, start


def mean(xs):
    xs = [x for x in xs if x is not None]
    return st.mean(xs) if xs else None


def pct(a, b):
    if a is None or b is None or a == 0:
        return None
    return (b - a) / a * 100.0


def fmt(v, digits=1):
    if v is None:
        return "n/a"
    return f"{v:.{digits}f}"


def fmt_pct(v):
    if v is None:
        return "n/a"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.1f}%"


def side_metrics(rows: list[dict], exclude_infra: bool) -> dict:
    tagged = [(r, *is_infra(r)) for r in rows]
    infra = [r for r, yes, _ in tagged if yes]
    kept = [r for r, yes, _ in tagged if not yes] if exclude_infra else list(rows)
    reasons = defaultdict(int)
    for r, yes, why in tagged:
        if yes:
            reasons[why] += 1

    n = len(rows)
    n_kept = len(kept)
    n_infra = len(infra)
    n_pass_raw = sum(1 for r in rows if r.get("success"))
    n_pass_kept = sum(1 for r in kept if r.get("success"))
    pass_raw = n_pass_raw / n if n else None
    pass_excl = n_pass_kept / n_kept if n_kept else None

    walls = [r.get("wall_time_s") for r in kept if isinstance(r.get("wall_time_s"), (int, float))]
    outs = [r.get("tokens_output") for r in kept if r.get("tokens_output") is not None]
    uncs = [
        r.get("tokens_input_uncached")
        for r in kept
        if r.get("tokens_input_uncached") is not None
    ]
    toks = [cell_tok(r) for r in kept]
    toks = [t for t in toks if t is not None]
    costs = [c for c in (row_cost(r) for r in kept) if c is not None]

    return {
        "n": n,
        "n_kept": n_kept,
        "n_infra": n_infra,
        "pass_raw": pass_raw,
        "pass_excl": pass_excl,
        "n_pass_raw": n_pass_raw,
        "n_pass_kept": n_pass_kept,
        "wall": mean(walls),
        "out": mean(outs),
        "unc": mean(uncs),
        "tok": mean(toks),
        "cost": mean(costs),
        "reasons": dict(reasons),
        "infra_rows": infra,
        "kept_rows": kept,
    }


def asymmetric(a_infra: int, b_infra: int, n: int) -> bool:
    diff = abs(a_infra - b_infra)
    if diff >= ASYM_ABS:
        return True
    if n > 0 and (diff / n) > ASYM_FRAC:
        return True
    return False


def floor_mark(delta, key: str) -> str:
    if delta is None:
        return "?"
    band = NOISE[key]
    return "OUTSIDE" if abs(delta) > band else "inside"


def score_pr(pr: int) -> dict:
    wo = load_side(pr, "without")
    wi = load_side(pr, "with")
    old_wo = side_metrics(wo, exclude_infra=False)
    old_wi = side_metrics(wi, exclude_infra=False)
    new_wo = side_metrics(wo, exclude_infra=True)
    new_wi = side_metrics(wi, exclude_infra=True)

    def deltas(a, b):
        return {
            "wall": pct(a["wall"], b["wall"]),
            "out": pct(a["out"], b["out"]),
            "unc": pct(a["unc"], b["unc"]),
            "tok": pct(a["tok"], b["tok"]),
            "cost": pct(a["cost"], b["cost"]),
        }

    old_d = deltas(old_wo, old_wi)
    new_d = deltas(new_wo, new_wi)
    gap = None
    if new_d["tok"] is not None and new_d["cost"] is not None:
        gap = abs(new_d["tok"] - new_d["cost"])

    asym = asymmetric(new_wo["n_infra"], new_wi["n_infra"], max(new_wo["n"], new_wi["n"]))

    # time windows of excluded cells
    def windows(rows):
        out = []
        for r in rows:
            s, e = window(r)
            out.append(
                {
                    "path": r["_path"],
                    "task": r.get("task"),
                    "trial": r.get("trial"),
                    "fc": r.get("failure_class"),
                    "start": s,
                    "end": e,
                    "out": r.get("tokens_output"),
                }
            )
        out.sort(key=lambda x: (x["start"] or datetime.min, x["path"]))
        return out

    return {
        "pr": pr,
        "old_wo": old_wo,
        "old_wi": old_wi,
        "new_wo": new_wo,
        "new_wi": new_wi,
        "old_d": old_d,
        "new_d": new_d,
        "gap_pp": gap,
        "asym": asym,
        "infra_wo": windows(new_wo["infra_rows"]),
        "infra_wi": windows(new_wi["infra_rows"]),
    }


def task_breakdown_13331_output(rec: dict) -> list[dict]:
    """Per-task output means after infra exclusion for #13331."""
    by = defaultdict(lambda: {"wo": [], "wi": []})
    for r in rec["new_wo"]["kept_rows"]:
        by[r.get("task")]["wo"].append(r.get("tokens_output"))
    for r in rec["new_wi"]["kept_rows"]:
        by[r.get("task")]["wi"].append(r.get("tokens_output"))
    # also count infra per task
    infra_by = defaultdict(lambda: {"wo": 0, "wi": 0})
    for r in rec["new_wo"]["infra_rows"]:
        infra_by[r.get("task")]["wo"] += 1
    for r in rec["new_wi"]["infra_rows"]:
        infra_by[r.get("task")]["wi"] += 1

    rows = []
    for task in sorted(set(by) | set(infra_by)):
        wo = [x for x in by[task]["wo"] if x is not None]
        wi = [x for x in by[task]["wi"] if x is not None]
        rows.append(
            {
                "task": task,
                "n_wo": len(wo),
                "n_wi": len(wi),
                "infra_wo": infra_by[task]["wo"],
                "infra_wi": infra_by[task]["wi"],
                "out_wo": mean(wo),
                "out_wi": mean(wi),
                "out_d": pct(mean(wo), mean(wi)),
            }
        )
    return rows


def overlap_note(recs: list[dict]) -> str:
    """Describe whether excluded-cell windows overlap across sides/PRs."""
    intervals = []  # (pr, side, start, end, path)
    for rec in recs:
        for side, wins in (("without", rec["infra_wo"]), ("with", rec["infra_wi"])):
            for w in wins:
                if w["start"] and w["end"]:
                    intervals.append((rec["pr"], side, w["start"], w["end"], w["path"]))
    if not intervals:
        return "No infra-excluded cells with timestamps among scored rows."

    # pairwise overlap count across different (pr,side)
    overlaps = []
    for i, a in enumerate(intervals):
        for b in intervals[i + 1 :]:
            if (a[0], a[1]) == (b[0], b[1]):
                continue
            # overlap if ranges intersect
            if a[2] <= b[3] and b[2] <= a[3]:
                overlaps.append((a, b))

    # cluster by day-hour buckets of start
    buckets = defaultdict(list)
    for pr, side, s, e, path in intervals:
        buckets[s.strftime("%Y-%m-%d %H:00")].append(f"#{pr}/{path}")

    lines = [
        f"Excluded cells with windows: {len(intervals)}; "
        f"cross-(pr,side) overlapping pairs: {len(overlaps)}."
    ]
    busy = sorted(buckets.items(), key=lambda kv: -len(kv[1]))[:8]
    lines.append("Start-hour buckets (top):")
    for hour, items in busy:
        lines.append(f"  {hour} ET — {len(items)} excl: " + ", ".join(items[:6])
                     + ("…" if len(items) > 6 else ""))
    if overlaps:
        # summarize unique pr-side pairs that overlap
        pairs = sorted({(f"#{a[0]}/{a[1]}", f"#{b[0]}/{b[1]}") for a, b in overlaps})
        lines.append("Overlapping (pr/side) pairs (sample): " + ", ".join(
            f"{x}∩{y}" for x, y in pairs[:12]
        ) + ("…" if len(pairs) > 12 else ""))
        lines.append(
            "Interpretation: overlapping windows across sides/PRs are consistent "
            "with a shared time-based rate-limit/timeout burst rather than a "
            "build-only effect."
        )
    else:
        lines.append(
            "No cross-(pr,side) window overlaps — exclusions look locally "
            "isolated (less like one global burst)."
        )
    return "\n".join(lines)


def validate_13331_webcore() -> list[str]:
    lines = ["### Classifier validation vs #13331 webcore (brief)"]
    for side in ("without", "with"):
        for p in sorted((CELLS / "13331" / "cells" / side / "webcore").glob("*.json")):
            d = json.loads(p.read_text())
            yes, why = is_infra(d)
            lines.append(
                f"- {side}/webcore/{p.stem}.json  fc={d.get('failure_class')}  "
                f"out={d.get('tokens_output')}  error={d.get('error')!r}  "
                f"→ infra={yes} ({why or 'kept'})"
            )
    return lines


def render_table(recs: list[dict]) -> list[str]:
    lines = []
    lines.append(
        "| PR | n kept/infra (wo→wi) | Pass excl (raw) | Wall Δ% old→new | "
        "Out Δ% old→new | Unc-in Δ% old→new | Tok/cell Δ% old→new | "
        "$/cell Δ% old→new | |tok−$| | Floor (wall/tok/$) | Flags |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for rec in recs:
        wo, wi = rec["new_wo"], rec["new_wi"]
        od, nd = rec["old_d"], rec["new_d"]
        flags = []
        if rec["asym"]:
            flags.append("ASYM_EXCL")
        if rec["gap_pp"] is not None and rec["gap_pp"] > TOK_COST_FLAG_PP:
            flags.append(f"TOK$={rec['gap_pp']:.1f}pp")
        # reclassified count = infra under new rule (all infra are 'excluded')
        floor = (
            f"{floor_mark(nd['wall'], 'wall')}/"
            f"{floor_mark(nd['tok'], 'tok')}/"
            f"{floor_mark(nd['cost'], 'cost')}"
        )
        # note: noise floor only claimed for hard5 first-pass; still mark all
        ncell = f"{wo['n_kept']}/{wo['n_infra']}→{wi['n_kept']}/{wi['n_infra']}"
        pass_s = (
            f"{fmt(wo['pass_excl'],3)}→{fmt(wi['pass_excl'],3)} "
            f"({fmt(wo['pass_raw'],3)}→{fmt(wi['pass_raw'],3)})"
        )

        def odnd(key):
            return f"{fmt_pct(od[key])}→{fmt_pct(nd[key])}"

        lines.append(
            f"| {rec['pr']} | {ncell} | {pass_s} | {odnd('wall')} | {odnd('out')} | "
            f"{odnd('unc')} | {odnd('tok')} | {odnd('cost')} | "
            f"{fmt(rec['gap_pp'],1) if rec['gap_pp'] is not None else 'n/a'} | "
            f"{floor} | {','.join(flags) or '—'} |"
        )
    return lines


def render_detail(rec: dict) -> list[str]:
    lines = [f"### PR #{rec['pr']}"]
    wo, wi = rec["new_wo"], rec["new_wi"]
    lines.append(
        f"- Reclassified/excluded: without **{wo['n_infra']}** "
        f"(reasons {wo['reasons'] or '{}'}), with **{wi['n_infra']}** "
        f"(reasons {wi['reasons'] or '{}'})."
    )
    lines.append(
        f"- Kept for means: {wo['n_kept']}/{wo['n']} without, "
        f"{wi['n_kept']}/{wi['n']} with."
    )
    if rec["asym"]:
        lines.append(
            f"- **ASYMMETRIC EXCLUSION** — infra counts {wo['n_infra']} vs "
            f"{wi['n_infra']} (diff≥{ASYM_ABS} or >{ASYM_FRAC:.0%} of n); "
            "surviving means are not comparable."
        )
    else:
        lines.append(
            f"- Exclusion balance: without {wo['n_infra']} / with {wi['n_infra']} "
            "(not flagged asymmetric)."
        )

    nd = rec["new_d"]
    lines.append(
        f"- New means (excl infra): wall {fmt(wo['wall'],1)}→{fmt(wi['wall'],1)} s "
        f"({fmt_pct(nd['wall'])}); out {fmt(wo['out'],0)}→{fmt(wi['out'],0)} "
        f"({fmt_pct(nd['out'])}); unc-in {fmt(wo['unc'],1)}→{fmt(wi['unc'],1)} "
        f"({fmt_pct(nd['unc'])}); tok/cell {fmt(wo['tok'],0)}→{fmt(wi['tok'],0)} "
        f"({fmt_pct(nd['tok'])}); $/cell {fmt(wo['cost'],4)}→{fmt(wi['cost'],4)} "
        f"({fmt_pct(nd['cost'])})."
    )
    lines.append(
        f"- Pass excl: {fmt(wo['pass_excl'],3)}→{fmt(wi['pass_excl'],3)} "
        f"({wo['n_pass_kept']}/{wo['n_kept']}→{wi['n_pass_kept']}/{wi['n_kept']}); "
        f"raw: {fmt(wo['pass_raw'],3)}→{fmt(wi['pass_raw'],3)} "
        f"({wo['n_pass_raw']}/{wo['n']}→{wi['n_pass_raw']}/{wi['n']})."
    )
    lines.append(
        f"- vs noise floor (±{NOISE['wall']:.0f}% wall / ±{NOISE['tok']:.0f}% tok / "
        f"±{NOISE['cost']:.0f}% $): wall {floor_mark(nd['wall'],'wall')}, "
        f"tok {floor_mark(nd['tok'],'tok')}, cost {floor_mark(nd['cost'],'cost')} "
        "(mark only; no CLEAR claim)."
    )

    # excluded windows
    def fmt_win(w):
        s = w["start"].strftime("%H:%M:%S") if w["start"] else "?"
        e = w["end"].strftime("%H:%M:%S") if w["end"] else "?"
        return (
            f"{w['path']} fc={w['fc']} out={w['out']} "
            f"window={s}–{e} ET"
        )

    if rec["infra_wo"] or rec["infra_wi"]:
        lines.append("- Excluded-cell time windows (ts_iso≈start + wall):")
        for w in rec["infra_wo"]:
            lines.append(f"  - without: {fmt_win(w)}")
        for w in rec["infra_wi"]:
            lines.append(f"  - with: {fmt_win(w)}")
    else:
        lines.append("- No cells excluded on either side.")
    return lines


def main():
    print("=== CLASSIFIER RULE ===")
    print(
        "infra if: failure_class ∈ {infra, rate_limited, stalled, timeout}\n"
        "  OR unsuccessful blob matches rate-limit (429|overloaded|RESOURCE_EXHAUSTED|rate_limit)\n"
        "  OR unsuccessful/incomplete blob matches timeout (timeout after|harness timeout|killed|deadline)\n"
        "  OR short-wall (<8s) unsuccessful exit-N / Unhandled-chunk death with ≤32 out tokens\n"
        "     (does not promote failure_class=incompatible).\n"
        "Excluded from wall/token/$ means. Pass reported as excl-infra and raw."
    )
    print()
    for line in validate_13331_webcore():
        print(line)
    print()

    recs = [score_pr(pr) for pr in ALL_SCORE]
    print("=== COMPACT TABLE (old→new Δ%) ===")
    for line in render_table(recs):
        print(line)
    print()

    # 4204 infra only
    print("=== #4204 off-sheet infra counts ===")
    for side in ("without", "with"):
        rows = load_side(4204, side)
        m = side_metrics(rows, exclude_infra=True)
        n_fc_infra = sum(1 for r in rows if r.get("failure_class") == "infra")
        n_incompat = sum(1 for r in rows if r.get("failure_class") == "incompatible")
        print(
            f"  {side}: n={m['n']} classifier_infra={m['n_infra']} "
            f"(failure_class=infra {n_fc_infra}, incompatible {n_incompat}) "
            f"kept={m['n_kept']} reasons={m['reasons']}"
        )
    print()

    print("=== PER-ROW NOTES ===")
    for rec in recs:
        for line in render_detail(rec):
            print(line)
        print()

    # 13331 per-task output after exclusion
    rec133 = next(r for r in recs if r["pr"] == 13331)
    print("=== #13331 per-task output Δ% after exclusion ===")
    print("| task | n_wo/n_wi (infra wo/wi) | out wo→wi | out Δ% |")
    print("|---|---|---|---|")
    for t in task_breakdown_13331_output(rec133):
        print(
            f"| {t['task']} | {t['n_wo']}/{t['n_wi']} "
            f"({t['infra_wo']}/{t['infra_wi']}) | "
            f"{fmt(t['out_wo'],0)}→{fmt(t['out_wi'],0)} | {fmt_pct(t['out_d'])} |"
        )
    print()

    print("=== TIME-CLUSTER / OVERLAP ===")
    print(overlap_note(recs + [score_pr(4204)]))

    # Also return structured summary path for report append
    return recs


if __name__ == "__main__":
    main()
