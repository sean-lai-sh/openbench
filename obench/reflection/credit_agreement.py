"""A/B agreement table for credit assignment (SEA-111).

One row per drawn failure (``credit_draw.json``, status ``IN``) that has
both a Method A row and a Method B row. Admitted failures that were not
drawn are absent. Summary counts are over those drawn rows only. A missing
draw file is an error. The pilot compares the two methods here: how early
Method B's window is ``near_error``, and whether Method A's first failure
is a probe error. Method A is unchanged. This module does not call a model.

``same_step`` is kept and is tautological. Method B's first failing step is
the shared locator step Method A records, because B's window is built from
that step. ``earliest_near_error_step`` is the comparison that can differ:
the earliest step in B's window labelled ``near_error``. ``steps_before_a``
is Method A's step minus that step.

A probe error is a tool error (``tool_error_status`` or ``tool_error_output``)
at step 3 or earlier. ``final_answer_rejected`` is not a probe error.

    python3 -m obench.reflection.credit_agreement --run <run dir>
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from obench.reflection import runner as rn
from obench.reflection.credit_draw import drawn_picks

SCHEMA = "openbench.reflection.credit_agreement/v1"
TABLE = "credit_agreement.jsonl"
PROBE_ERROR_MAX_STEP = 3
PROBE_SIGNALS = ("tool_error_status", "tool_error_output")


def is_probe_error(step, signal: str | None) -> bool:
    """True when Method A's first failure is a tool error at step 3 or earlier."""
    if isinstance(step, bool) or not isinstance(step, int):
        return False
    return 1 <= step <= PROBE_ERROR_MAX_STEP and signal in PROBE_SIGNALS


def _label_at(labels: dict, step: int):
    if str(step) in labels:
        return labels[str(step)]
    return labels.get(step)


def earliest_near_error_step(method_b: dict) -> int | None:
    """Earliest window step labelled ``near_error``.

    Null when the window is empty (``empty_window``), the trace is empty,
    the judge failed, or no window step is ``near_error``.
    """
    if method_b.get("status") in ("empty_window", "empty_trace", "judge_error"):
        return None
    labels = method_b.get("labels") or {}
    if not isinstance(labels, dict):
        return None
    found = []
    for step in method_b.get("window") or []:
        if isinstance(step, bool) or not isinstance(step, int):
            continue
        if _label_at(labels, step) == "near_error":
            found.append(step)
    return min(found) if found else None


def agreement_row(method_a: dict, method_b: dict) -> dict:
    labels = method_b.get("labels") or {}
    near = sorted(int(step) for step, label in labels.items() if label == "near_error")
    a_step, b_step = method_a.get("failing_step"), method_b.get("first_failing_step")
    signal = method_a.get("signal")
    probe = is_probe_error(a_step, signal)
    window = list(method_b.get("window") or [])
    earliest = earliest_near_error_step(method_b)
    steps_before = None
    if earliest is not None and not isinstance(a_step, bool) and isinstance(a_step, int):
        steps_before = a_step - earliest
    return {
        "schema": SCHEMA, "trial_id": method_a["trial_id"], "task": method_a.get("task"),
        "model": method_a.get("model"), "patch_id": method_a.get("patch_id"),
        "drawn": True,
        "method_a_step": a_step, "method_a_signal": signal,
        "method_b_step": b_step, "method_b_status": method_b.get("status"),
        "method_b_window": window,
        "method_b_window_length": method_b.get("window_length", len(window)),
        "same_step": a_step is not None and a_step == b_step,
        "earliest_near_error_step": earliest, "steps_before_a": steps_before,
        "near_error_steps": near, "near_error_count": len(near),
        "probe_error": probe, "probe_error_step": a_step if probe else None,
    }


def run_agreement(run_dir: Path) -> list[dict]:
    """Write ``credit_agreement.jsonl`` for drawn failures only. A rerun replaces it.

    The table is the pre-registered draw (status ``IN``), not the overlap of
    the two credit tables. Method A still covers every admitted failure.
    A drawn trial missing either credit row is an error. Counts over the
    returned rows are counts over drawn failures only.
    """
    run_dir = Path(run_dir)
    picks = drawn_picks(run_dir)
    method_a = {row["trial_id"]: row for row in rn.read_rows(run_dir / "credit_a.jsonl")}
    method_b = {row["trial_id"]: row for row in rn.read_rows(run_dir / "credit_b.jsonl")}
    missing = [pick["trial_id"] for pick in picks if pick["trial_id"] not in method_a or pick["trial_id"] not in method_b]
    if missing:
        raise ValueError(f"drawn trials missing a Method A or Method B row: {missing}")
    rows = [agreement_row(method_a[pick["trial_id"]], method_b[pick["trial_id"]]) for pick in picks]
    tmp = run_dir / (TABLE + ".tmp")
    tmp.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    os.replace(tmp, run_dir / TABLE)
    return rows


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="A/B agreement table for credit assignment")
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        rows = run_agreement(args.run)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    print(json.dumps({
        "rows": len(rows), "drawn": len(rows), "table": str(args.run / TABLE),
        "probe_errors": sum(1 for row in rows if row["probe_error"]),
        "same_step": sum(1 for row in rows if row["same_step"]),
        "earliest_near_error": sum(1 for row in rows if row["earliest_near_error_step"] is not None),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
