"""Credit assignment Method A: the first failing step (SEA-108).

For every failed trial in a runner run (``trials.jsonl``, completed and
not passed), Method A reads the trial's trace and records the first failing
step under the shared locator rule (``credit_locator``). It writes its own
table, ``credit_a.jsonl``, next to the run's tables. It never writes into
``trials.jsonl`` or Method B's table.

    python3 -m obench.reflection.credit_a --run <run dir>

Rule version: ``METHOD_A_RULE_VERSION`` = Method A version + the locator
version. Documented in CREDIT_ASSIGNMENT.md.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from obench.reflection.credit_locator import LOCATOR_RULE_VERSION, failed_trials, first_failure, read_trace

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
        "failing_step": found.step, "signal": found.signal, "tool": found.tool,
        "rationale": _RATIONALE[found.signal].format(step=found.step, tool=found.tool),
        "evidence": found.evidence, "steps_total": found.steps_total,
        "trace": trial.get("trace"),
        "trace_step": f"{trial.get('trace')}#step={found.step}" if trial.get("trace") and found.step else None,
    }


def run_method_a(run_dir: Path) -> list[dict]:
    """Write ``credit_a.jsonl`` for every failed trial of the run (rewritten
    whole, atomically, so a rerun is idempotent)."""
    run_dir = Path(run_dir)
    rows = []
    for trial in failed_trials(run_dir):
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
    args = parser.parse_args(argv)
    rows = run_method_a(args.run)
    print(json.dumps({"rows": len(rows), "table": str(args.run / TABLE), "rule_version": METHOD_A_RULE_VERSION}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
