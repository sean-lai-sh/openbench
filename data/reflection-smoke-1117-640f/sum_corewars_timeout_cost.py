#!/usr/bin/env python3
"""Sum the Smoke A Carbon winning-avg-corewars timeout cost from its wire.jsonl.

The trial (5a584347c1df32b9) has cost_usd=null in trials.jsonl because
obench/reflection/cell_executor.py at 640f6751 only writes a trial total when
every wire call has a cost. Call 11 has none: the proxy read timed out with
no response_usage. This script sums the per-call cost_usd fields that are
present and checks them against the Carbon list prices in
obench/reflection/vertex_models.py at the same head.
"""
from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path

# 640f675152bbbe31864bf47e14b81293aea249b7 obench/reflection/vertex_models.py
# gemini-4-carbon: price_verified=False, basis list_unverified.
# "global online-prediction SKU as reported for the Cloud catalog ($4/$20);
# Google announced an introductory $2/$10. Cache read assumed at 10% of input."
CARBON_USD_PER_1M = {"input": 4.0, "output": 20.0, "cache_read": 0.40}
PRICE_SOURCE = (
    "obench/reflection/vertex_models.py at "
    "640f675152bbbe31864bf47e14b81293aea249b7, gemini-4-carbon prices "
    "(input $4 / 1M, output $20 / 1M, cache_read $0.40 / 1M). "
    "price_verified=False. Quote: global online-prediction SKU as reported "
    "for the Cloud catalog ($4/$20); Google announced an introductory $2/$10. "
    "Cache read assumed at 10% of input. Confirm on the Agent Platform "
    "pricing page before any scored run."
)

WIRE_REL = (
    "smoke-a/run/trials/gemini-4-carbon/winning-avg-corewars/"
    "5a584347c1df32b9/wire.jsonl"
)


def _gemini_cost(usage: dict) -> float:
    """Same formula as vertex_models.cost_detail for wire=gemini."""
    inp = usage.get("promptTokenCount") or 0
    out = usage.get("candidatesTokenCount") or 0
    read = usage.get("cachedContentTokenCount") or 0
    thinking = usage.get("thoughtsTokenCount") or 0
    uncached = max(inp - read, 0)
    billed_out = out + thinking
    total = (
        uncached * CARBON_USD_PER_1M["input"]
        + billed_out * CARBON_USD_PER_1M["output"]
        + read * CARBON_USD_PER_1M["cache_read"]
    )
    return round(total / 1_000_000, 8)


def summarize(wire_path: Path) -> dict:
    calls = []
    unpriced = []
    by_role: dict[str, Decimal] = {}
    for line in wire_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        usage = rec.get("response_usage")
        entry = {
            "call_index": rec.get("call_index"),
            "call_role": rec.get("call_role"),
            "ts": rec.get("ts"),
            "cost_usd": rec.get("cost_usd"),
            "cost_basis": rec.get("cost_basis"),
            "error": rec.get("error"),
            "requested_model": rec.get("requested_model"),
            "upstream_model": rec.get("upstream_model"),
        }
        if usage is not None:
            recomputed = _gemini_cost(usage)
            entry["recomputed_usd"] = recomputed
            entry["recomputed_matches_wire"] = recomputed == rec.get("cost_usd")
            entry["usage"] = {
                "prompt_tokens": usage.get("promptTokenCount") or 0,
                "cached_tokens": usage.get("cachedContentTokenCount") or 0,
                "candidates_tokens": usage.get("candidatesTokenCount") or 0,
                "thinking_tokens": usage.get("thoughtsTokenCount") or 0,
            }
        calls.append(entry)
        if rec.get("cost_usd") is None:
            unpriced.append({
                "call_index": rec.get("call_index"),
                "call_role": rec.get("call_role"),
                "ts": rec.get("ts"),
                "error": rec.get("error"),
                "reason": "no response_usage" if usage is None else "cost_usd is null",
            })
        else:
            role = rec.get("call_role") or "unknown"
            by_role[role] = by_role.get(role, Decimal("0")) + Decimal(str(rec["cost_usd"]))

    priced = [c for c in calls if c["cost_usd"] is not None]
    cost = sum((Decimal(str(c["cost_usd"])) for c in priced), Decimal("0"))
    recomputed = sum(
        (Decimal(str(c["recomputed_usd"])) for c in priced if "recomputed_usd" in c),
        Decimal("0"),
    )
    # Original README / trials.jsonl figures (corewars excluded because it is null).
    smoke_a_excluding = Decimal("19.970348")
    smoke_b = Decimal("4.013069")
    return {
        "trial_id": "5a584347c1df32b9",
        "model": "gemini-4-carbon",
        "task": "winning-avg-corewars",
        "run": "smoke-a",
        "wire": WIRE_REL,
        "method": (
            "Sum of per-call cost_usd fields already written on the trial's "
            "wire.jsonl records. Call 11 is omitted because it has no cost "
            "field and no usage to price. trials.jsonl is not edited."
        ),
        "prices": {
            "usd_per_1m_tokens": CARBON_USD_PER_1M,
            "price_verified": False,
            "cost_basis": ["list_unverified"],
            "source": PRICE_SOURCE,
            "gemini_adjustments": (
                "promptTokenCount includes cached tokens; subtract cache "
                "before applying the input rate. candidatesTokenCount "
                "excludes thinking; add thoughtsTokenCount and bill the "
                "sum at the output rate. Same as "
                "obench/reflection/vertex_models.cost_detail."
            ),
        },
        "n_calls": len(calls),
        "n_priced_calls": len(priced),
        "unpriced_calls": unpriced,
        "cost_usd": float(cost),
        "by_role_usd": {k: float(v) for k, v in sorted(by_role.items())},
        "by_model_usd": {"gemini-4-carbon": float(cost)},
        "recomputed_from_usage_usd": float(recomputed),
        "recomputed_matches_wire": all(c.get("recomputed_matches_wire") for c in priced)
        and recomputed == cost,
        "original_smoke_a_trials_jsonl_usd": float(smoke_a_excluding),
        "original_smoke_a_reported_usd": 19.9703,
        "corrected_smoke_a_usd": float(smoke_a_excluding + cost),
        "smoke_b_trials_jsonl_usd": float(smoke_b),
        "original_combined_trials_jsonl_usd": 23.983417,
        "original_combined_reported_usd": 23.9834,
        "corrected_combined_usd": float(smoke_a_excluding + cost + smoke_b),
        "calls": sorted(calls, key=lambda c: c["call_index"] or 0),
    }


def main() -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--wire",
        type=Path,
        default=here / WIRE_REL,
        help="Path to the corewars timeout wire.jsonl",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=here / "smoke-a/corewars-timeout-cost.json",
        help="Where to write the summary JSON",
    )
    args = parser.parse_args()
    summary = summarize(args.wire)
    text = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(
        f"cost_usd={summary['cost_usd']} "
        f"corrected_smoke_a={summary['corrected_smoke_a_usd']} "
        f"corrected_combined={summary['corrected_combined_usd']} "
        f"wrote={args.out}"
    )
    return 0 if summary["recomputed_matches_wire"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
