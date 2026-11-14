"""First-failure locator shared by credit-assignment Methods A and B.

Rule ``LOCATOR_RULE_VERSION`` (documented in CREDIT_ASSIGNMENT.md):

1. Walk the failed trial's steps in order. A step **fails** when one of its
   tool calls carries an error signal: ``status == "error"`` (including
   errored calls recovered from the next request), or a result matching
   ``ERROR_PATTERNS`` (a traceback, a compiler/shell error, a non-zero exit,
   failing tests).
2. The first such step is the first failing step, **even if later steps
   recover from it**. The flag marks where the trajectory first went
   wrong, not where it ended.
3. If no step has an error signal, the trial failed silently: the last step
   that ended the run (it submitted a result the checker rejected) is the
   failing step, with signal ``final_answer_rejected``.
4. An empty trace has no failing step (``signal: "empty_trace"``).

Steps are the trace's 1-based ``step`` values (``openbench.reflection.step/v1``).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

LOCATOR_RULE_VERSION = "locator-v1"
ERROR_PATTERNS = (
    r"Traceback \(most recent call last\)",
    r"(?m)^\s*(error|fatal)(\[[A-Z0-9]+\])?:",
    r"\bcommand not found\b",
    r"\bNo such file or directory\b",
    r"\b(exit|exited with|exit code|returned non-zero exit status)\s*:?\s*[1-9][0-9]*\b",
    r"(?m)^\s*FAILED\b",
    r"\bSegmentation fault\b",
)
_PATTERNS = [re.compile(p, re.IGNORECASE) for p in ERROR_PATTERNS]
SIGNALS = ("tool_error_status", "tool_error_output", "final_answer_rejected", "empty_trace")


@dataclass(frozen=True)
class FirstFailure:
    step: int | None            # 1-based trace step, None for an empty trace
    signal: str                 # one of SIGNALS
    tool: str | None
    evidence: str               # short excerpt that triggered the signal
    steps_total: int
    rule_version: str = LOCATOR_RULE_VERSION

    def as_dict(self) -> dict:
        return asdict(self)


def _text(value) -> str:
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True) if value is not None else ""


def step_error(step: dict) -> tuple[str, str | None, str] | None:
    """``(signal, tool, evidence)`` for the step's first erroring tool call, or None."""
    for call in step.get("tool_calls") or []:
        result = _text(call.get("result"))
        if call.get("status") == "error":
            return "tool_error_status", call.get("name"), result[:200]
        for pattern in _PATTERNS:
            match = pattern.search(result)
            if match:
                start = max(match.start() - 60, 0)
                return "tool_error_output", call.get("name"), result[start:match.end() + 80]
    return None


def first_failure(steps: list[dict]) -> FirstFailure:
    ordered = sorted(steps, key=lambda s: s.get("step") or 0)
    if not ordered:
        return FirstFailure(step=None, signal="empty_trace", tool=None, evidence="", steps_total=0)
    for step in ordered:
        hit = step_error(step)
        if hit:
            signal, tool, evidence = hit
            return FirstFailure(step=step["step"], signal=signal, tool=tool, evidence=evidence,
                                steps_total=len(ordered))
    last = ordered[-1]
    return FirstFailure(step=last["step"], signal="final_answer_rejected", tool=None,
                        evidence=(last.get("assistant_text") or "")[:200], steps_total=len(ordered))


def read_trace(path: Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def failed_trials(run_dir: Path) -> list[dict]:
    """Completed, failing baseline-or-patch trial rows of a runner run (SEA-107)."""
    path = Path(run_dir) / "trials.jsonl"
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in rows if r.get("status") == "completed" and r.get("passed") is False]
