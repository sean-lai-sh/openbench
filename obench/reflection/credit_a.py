"""Credit assignment Method A: the first failing step (SEA-108).

For every failed trial in a runner run (``trials.jsonl``, completed and
not passed), Method A reads the trial's trace and records the first failing
step under the shared locator rule (``credit_locator``). It writes its own
table, ``credit_a.jsonl``, next to the run's tables. It never writes into
``trials.jsonl`` or Method B's table.

    python3 -m obench.reflection.credit_a --run <run dir> [--max-set-aside 3]

A cell enters when its set-aside trials (``provider_blocked`` and ``model_refused``)
are at most ``--max-set-aside`` (default 3, about 10% of 30). Each row records
``max_set_aside`` and that cell's ``set_aside_count``.

Rule version: ``METHOD_A_RULE_VERSION`` = Method A version + the locator
version. Documented in CREDIT_ASSIGNMENT.md.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from obench.reflection.credit_locator import (
    LOCATOR_RULE_VERSION, MAX_SET_ASIDE, failed_trials, first_failure, read_trace,
)

METHOD_A_SCHEMA = "openbench.reflection.credit_a/v1"
METHOD_A_RULE_VERSION = f"A1+{LOCATOR_RULE_VERSION}"
TABLE = "credit_a.jsonl"

_RATIONALE = {
    "tool_error_status": "step {step}: tool {tool!r} returned an error; first error signal in the trace",
    "tool_error_output": "step {step}: tool {tool!r} output shows an error; first error signal in the trace",
    "final_answer_rejected": "no step shows an error signal; step {step} ended the run with a result the checker rejected",
    "empty_trace": "the trace has no steps",
}


def method_a_row(trial: dict, steps: list[dict]) -> dict:
    found = first_failure(steps)
    return {
        "schema": METHOD_A_SCHEMA, "rule_version": METHOD_A_RULE_VERSION,
        "run_id": trial.get("run_id"), "trial_id": trial["trial_id"], "task": trial["task"],
        "model": trial["model"], "patch_id": trial.get("patch_id"),
        "set_aside_count": trial.get("set_aside_count", 0),
        "max_set_aside": trial.get("max_set_aside", MAX_SET_ASIDE),
        "failing_step": found.step, "signal": found.signal, "tool": found.tool,
        "rationale": _RATIONALE[found.signal].format(step=found.step, tool=found.tool),
        "evidence": found.evidence, "steps_total": found.steps_total,
        "trace": trial.get("trace"),
        "trace_step": f"{trial.get('trace')}#step={found.step}" if trial.get("trace") and found.step else None,
    }


def run_method_a(run_dir: Path, max_set_aside: int = MAX_SET_ASIDE) -> list[dict]:
    """Write ``credit_a.jsonl`` for every admitted failed trial of the run (rewritten
    whole, atomically, so a rerun is idempotent). A cell is admitted when its
    set-aside count is at most ``max_set_aside``."""
    run_dir = Path(run_dir)
    rows = []
    for trial in failed_trials(run_dir, max_set_aside=max_set_aside):
        steps = read_trace(run_dir / trial["trace"]) if trial.get("trace") else []
        rows.append(method_a_row(trial, steps))
    tmp = run_dir / (TABLE + ".tmp")
    tmp.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    os.replace(tmp, run_dir / TABLE)
    return rows


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Credit assignment Method A (first failing step)")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--max-set-aside", type=int, default=MAX_SET_ASIDE,
                        help="admit a cell when its set-aside trials are at most this many (default: 3, about 10%% of 30)")
    args = parser.parse_args(argv)
    rows = run_method_a(args.run, max_set_aside=args.max_set_aside)
    print(json.dumps({"rows": len(rows), "table": str(args.run / TABLE), "rule_version": METHOD_A_RULE_VERSION,
                      "max_set_aside": args.max_set_aside}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
