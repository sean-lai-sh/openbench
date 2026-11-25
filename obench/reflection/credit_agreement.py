"""A/B agreement table for credit assignment (SEA-111).

One row per failed trial that has both a Method A row and a Method B row.
The pilot compares the two methods here: the same first-failure step, how
often Method B's window is ``near_error``, and whether Method A's first
failure is a probe error. Method A is unchanged. This module does not call
a model.

A probe error is a tool error (``tool_error_status`` or ``tool_error_output``)
at step 3 or earlier. ``final_answer_rejected`` is not a probe error.

    python3 -m obench.reflection.credit_agreement --run <run dir>
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from obench.reflection import runner as rn

SCHEMA = "openbench.reflection.credit_agreement/v1"
TABLE = "credit_agreement.jsonl"
PROBE_ERROR_MAX_STEP = 3
PROBE_SIGNALS = ("tool_error_status", "tool_error_output")


def is_probe_error(step, signal: str | None) -> bool:
    """True when Method A's first failure is a tool error at step 3 or earlier."""
    if isinstance(step, bool) or not isinstance(step, int):
        return False
    return 1 <= step <= PROBE_ERROR_MAX_STEP and signal in PROBE_SIGNALS


def agreement_row(method_a: dict, method_b: dict) -> dict:
    labels = method_b.get("labels") or {}
    near = sorted(int(step) for step, label in labels.items() if label == "near_error")
    a_step, b_step = method_a.get("failing_step"), method_b.get("first_failing_step")
    signal = method_a.get("signal")
    probe = is_probe_error(a_step, signal)
    window = list(method_b.get("window") or [])
    return {
        "schema": SCHEMA, "trial_id": method_a["trial_id"], "task": method_a.get("task"),
        "model": method_a.get("model"), "patch_id": method_a.get("patch_id"),
        "method_a_step": a_step, "method_a_signal": signal,
        "method_b_step": b_step, "method_b_status": method_b.get("status"),
        "method_b_window": window,
        "method_b_window_length": method_b.get("window_length", len(window)),
        "same_step": a_step is not None and a_step == b_step,
        "near_error_steps": near, "near_error_count": len(near),
        "probe_error": probe, "probe_error_step": a_step if probe else None,
    }


def run_agreement(run_dir: Path) -> list[dict]:
    """Write ``credit_agreement.jsonl`` from the two credit tables. A rerun replaces it."""
    run_dir = Path(run_dir)
    method_a = {row["trial_id"]: row for row in rn.read_rows(run_dir / "credit_a.jsonl")}
    method_b = {row["trial_id"]: row for row in rn.read_rows(run_dir / "credit_b.jsonl")}
    rows = [agreement_row(method_a[trial_id], method_b[trial_id]) for trial_id in method_a if trial_id in method_b]
    tmp = run_dir / (TABLE + ".tmp")
    tmp.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    os.replace(tmp, run_dir / TABLE)
    return rows


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="A/B agreement table for credit assignment")
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args(argv)
    rows = run_agreement(args.run)
    print(json.dumps({
        "rows": len(rows), "table": str(args.run / TABLE),
        "probe_errors": sum(1 for row in rows if row["probe_error"]),
        "same_step": sum(1 for row in rows if row["same_step"]),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
