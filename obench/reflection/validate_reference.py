"""Run a task's reference solution in the trial container and grade it with checker.sh.

No model calls and no proxy. The workspace is seeded the way ``CellExecutor`` seeds a trial,
``solve.sh`` / ``solution.sh`` runs in the task image on the trial network (or ``solution/`` is
overlaid when that is the reference), and ``CellExecutor._check`` runs the same checker command
a trial uses. Rows go to ``oracle.jsonl``, never ``trials.jsonl``. A task with no reference
solution is ``no_reference``.

    python3 -m obench.reflection.validate_reference --task extract-elf --task sanitize-git-repo --out oracle.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from obench.hardsuite.suite import SuiteError, load_suite
from obench.reflection.cell_executor import CellExecutor
from obench.reflection.runner import TrialSpec, _append, code_commit, host_name
from obench.workspace import overlay_solution

ORACLE_SCHEMA = "openbench.reflection.oracle/v1"
_TAIL = 8000
_SOLVE_NAMES = ("solve.sh", "solution.sh")


def find_reference(task_dir: Path) -> dict:
    """``{kind, path}``. ``kind`` is ``solve.sh``, ``solution.sh``, ``overlay``, or ``no_reference``."""
    sol = Path(task_dir) / "solution"
    if not sol.is_dir():
        return {"kind": "no_reference", "path": None}
    for name in _SOLVE_NAMES:
        script = sol / name
        if script.is_file() and script.stat().st_size > 0:
            return {"kind": name, "path": script}
    files = [p for p in sol.rglob("*") if p.is_file() and p.name != ".gitkeep" and p.stat().st_size > 0]
    if files:
        return {"kind": "overlay", "path": sol}
    return {"kind": "no_reference", "path": None}


def _tail_file(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text[-_TAIL:], encoding="utf-8")
    return str(path)


def _rel(out: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(out.parent.resolve()))
    except ValueError:
        return str(path)


def validate_one(executor, tasks_dir: str, task: str, work_root: Path, out: Path) -> dict:
    """One oracle row. ``executor`` is a ``CellExecutor`` (or a test double with the same methods)."""
    started = time.monotonic()
    task_dir = Path(tasks_dir) / task
    ref = find_reference(task_dir)
    head = code_commit().get("commit")
    dest = work_root / task
    workspace = dest / "workspace"
    row = {"schema": ORACLE_SCHEMA, "task": task, "image": None, "image_digest": None, "head": head,
           "host": host_name(), "reference": ref["kind"], "status": "no_reference", "passed": None,
           "checker_exit": None, "duration_s": None, "network": None, "stdout_tail": None, "stderr_tail": None,
           "checker_output": None, "error": None}
    if ref["kind"] == "no_reference":
        row["duration_s"] = round(time.monotonic() - started, 3)
        return row
    spec = TrialSpec(run_id="oracle", trial_id="oracle", task=task, tasks_dir=str(tasks_dir), model="",
                     trial_index=0, patch_id=None, patch=None, trial_dir="")
    try:
        probe = getattr(executor, "isolation_preflight", None)
        if probe is not None:
            probe()
        info = executor.resolve_image(executor._task(spec), task)
        image = executor.image_record(info)
        row["image"], row["image_digest"] = image.get("ref"), image.get("id")
        network = executor.agent_network(info)
        row["network"] = network
        if workspace.exists():
            import shutil
            shutil.rmtree(workspace)
        workspace.mkdir(parents=True)
        executor.seed_workspace(info, workspace)
        solve_exit = None
        if ref["kind"] in _SOLVE_NAMES:
            stdout_path, stderr_path = dest / "solve-stdout.txt", dest / "solve-stderr.txt"
            solve_exit, stdout, stderr = executor.run_solve(info, workspace, ref["path"], network, stdout_path, stderr_path)
            row["stdout_tail"] = _rel(out, Path(_tail_file(dest / "solve-stdout.tail", stdout)))
            row["stderr_tail"] = _rel(out, Path(_tail_file(dest / "solve-stderr.tail", stderr)))
            row["solve_exit"] = solve_exit
        else:
            overlay_solution(str(task_dir), str(workspace))
        # The checker runs after the reference is applied, same as a trial grades the workspace it was given.
        checker_exit, _mode, output = executor._check(info, workspace)
        checker_path = dest / "checker-stdout.txt"
        checker_path.write_text(output or "", encoding="utf-8")
        tail = dest / "checker-stdout.tail"
        _tail_file(tail, output or "")
        row["checker_exit"] = checker_exit
        row["checker_output"] = _rel(out, tail)
        row["passed"] = checker_exit == 0
        row["status"] = "pass" if checker_exit == 0 else "fail"
        if solve_exit not in (0, None):
            row["error"] = f"{ref['kind']} exited {solve_exit}"
    except Exception as exc:  # image missing, isolation, docker: recorded, not a crash of the command
        row["status"] = "error"
        row["error"] = f"{type(exc).__name__}: {exc}"
    row["duration_s"] = round(time.monotonic() - started, 3)
    return row


def validate_tasks(executor, tasks: list[tuple[str, str]], out: Path) -> list[dict]:
    out = Path(out)
    if out.name == "trials.jsonl":
        raise SystemExit("refusing to write reference results to trials.jsonl; use oracle.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    work = out.parent / (out.stem + "-work")
    rows = []
    for tasks_dir, task in tasks:
        row = validate_one(executor, tasks_dir, task, work, out)
        _append(out, row)
        rows.append(row)
    return rows


def resolve_task_names(names: list[str], suite_name: str) -> list[tuple[str, str]]:
    try:
        suite = load_suite(suite_name)
        known = {t.id: t for t in suite.tasks}
        if suite.pool:
            known.update({t.id: t for t in load_suite(suite.pool).tasks})
    except (OSError, SuiteError) as exc:
        raise SystemExit(str(exc)) from exc
    missing = [name for name in names if name not in known]
    if missing:
        raise SystemExit(f"not in suite {suite_name!r} or its pool: {missing}")
    return [(str(known[name].tasks_dir), name) for name in names]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Grade hardsuite reference solutions with the trial checker")
    parser.add_argument("--task", action="append", required=True, help="task id (repeat for several)")
    parser.add_argument("--suite", default="pilot")
    parser.add_argument("--out", type=Path, default=Path("oracle.jsonl"))
    parser.add_argument("--default-image", default="h1-env:1027-strace")
    parser.add_argument("--use-image-tag", action="store_true")
    args = parser.parse_args(argv)
    if any(part in ("results", "data") for part in args.out.expanduser().resolve().parts):
        raise SystemExit("--out must be outside results/ and data/")
    tasks = resolve_task_names(args.task, args.suite)
    # No OpenCode and no proxy: the checker and the reference container are the trial paths.
    executor = CellExecutor(opencode=None, project="", token=lambda: "", check_pin=False,
                            default_image=args.default_image, use_image_tag=args.use_image_tag)
    rows = validate_tasks(executor, tasks, args.out)
    print(json.dumps([{"task": r["task"], "status": r["status"], "checker_exit": r["checker_exit"]} for r in rows],
                     indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
