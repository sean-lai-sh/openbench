"""Explicit pass/fail lines for thesis checkers.

A thesis cell (every task under ``tasks/``, including ``trig-*``) is correct
or wrong only when the checker exit code and a final ``OBENCH_VERDICT`` line
agree:

* exit 0 and ``OBENCH_VERDICT: pass``
* exit 1 and ``OBENCH_VERDICT: fail``

Exit 2 is a deliberate infra result (for example a missing dotnet SDK). A
missing line, a traceback with no agreeing line, exit 126/127, or a checker
timeout is infra too. Imported Terminal-Bench and Exercism graders do not
print the line and keep the exit-code contract.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

VERDICT_PASS = "OBENCH_VERDICT: pass"
VERDICT_FAIL = "OBENCH_VERDICT: fail"
_VERDICT_RE = re.compile(r"^OBENCH_VERDICT:\s*(pass|fail)\s*$", re.MULTILINE)
_CRASH_REASON = "checker_crash"


def repo_tasks_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "tasks"


def thesis_task_names() -> frozenset[str]:
    root = repo_tasks_dir()
    if not root.is_dir():
        return frozenset()
    names = set()
    for path in root.iterdir():
        if path.is_dir() and (path / "checker.sh").is_file():
            names.add(path.name)
    return frozenset(names)


def thesis_task_name(name: str | None) -> bool:
    """True for tasks the thesis A/B runner scores from this repo's ``tasks/``."""
    text = str(name or "")
    if not text:
        return False
    if text.startswith("trig-"):
        return True
    return text in thesis_task_names()


def expects_explicit_verdict(task_dir: str | None) -> bool:
    if not task_dir:
        return False
    return thesis_task_name(os.path.basename(os.path.abspath(task_dir)))


def parse_verdict(text: str | None) -> str | None:
    """Return the last ``pass`` or ``fail`` verdict in ``text``."""
    found = _VERDICT_RE.findall(text or "")
    if not found:
        return None
    return found[-1]


def verdict_agrees(exit_code, text: str | None) -> bool:
    """True when a graded exit and the verdict line name the same result."""
    verdict = parse_verdict(text)
    if exit_code == 0 and verdict == "pass":
        return True
    if exit_code == 1 and verdict == "fail":
        return True
    return False


def crash_reason(exit_code, stdout: str | None, stderr: str | None) -> str:
    """Stable infra reason, including the exception line and a stderr tail."""
    err = (stderr or "").strip()
    interesting = ""
    for line in err.splitlines():
        stripped = line.strip()
        if "Error" in stripped or stripped.startswith("Traceback"):
            interesting = stripped
    if exit_code == "timeout":
        head = f"{_CRASH_REASON}: timeout"
    elif interesting and "Error" in interesting:
        head = f"{_CRASH_REASON}: {interesting}"
    else:
        head = f"{_CRASH_REASON}: exit {exit_code}"
    if not err:
        out = (stdout or "").strip()
        if out and out not in head:
            return head + "\n" + out[-400:]
        return head
    tail = err[-400:]
    if tail in head:
        return head
    return head + "\n" + tail


def prepend_checker_pythonpath(env: dict) -> None:
    """Let a checker ``import obench`` from the checkout without an install."""
    from .paths import SOURCE_ROOT

    root = SOURCE_ROOT
    current = env.get("PYTHONPATH") or ""
    parts = [part for part in current.split(os.pathsep) if part]
    if root in parts:
        return
    env["PYTHONPATH"] = root if not parts else root + os.pathsep + current


def repo_root_from_task_dir(task_dir: str) -> str:
    """``tasks/<name>`` → the checkout that contains the ``obench`` package."""
    return str(Path(task_dir).resolve().parents[1])


def apply_explicit_verdict(row, checker_exit, raw_score, classify, classify_reason,
                           adapter_output="", timeout_s=None):
    """Grade a thesis cell. Agreeing exit and verdict stay pass/fail; else infra.

    ``classify`` and ``classify_reason`` are the runner's failure-taxonomy
    callables. A crash reason starts with ``checker_crash`` so a later report
    pass cannot promote the cell to a wrong answer.
    """
    stdout = row.get("checker_stdout") or ""
    stderr = row.get("checker_stderr") or ""
    if verdict_agrees(checker_exit, stdout):
        row["success"] = checker_exit == 0
        if checker_exit == 0:
            row["score"] = 1.0
        else:
            row["score"] = raw_score if raw_score is not None else 0.0
        row["failure_class"] = classify(row, adapter_output, timeout_s)
        row["failure_reason"] = classify_reason(row, adapter_output)
        return row
    row["success"] = False
    row["score"] = 0.0
    row["failure_class"] = "infra"
    row["failure_reason"] = crash_reason(checker_exit, stdout, stderr)
    return row
