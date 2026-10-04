"""Build both sides of each pull request and run the same tasks on each binary.

Cells land in their own files. The parent rewrites each side's JSONL from
those files after a cell finishes. A binary that cannot load the Vertex model
records ``<side>.incompatible.json`` and does not produce a score.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path

from obench.validate_tasks import build_task_roots, discover_tasks

from thesis.ab.build_opencode import BuildError, binary
from thesis.ab.compat import assess
from thesis.ab.durable import publish_text
from thesis.ab.prs import PrListError, Side, parse_prs, select_prs
from thesis.ab.summarize import row_cost

CHECKER_TIMEOUT_S = 120


class RunError(ValueError):
    pass


def core_task_names(tasks_dir: Path | None = None) -> tuple[str, ...]:
    if tasks_dir is None:
        roots = build_task_roots(include_imported=False)
    else:
        roots = [("core", str(tasks_dir))]
    return tuple(name for _tier, name, _path in discover_tasks(roots))


def resolve_tasks(wanted: list[str] | None, tasks_dir: Path | None = None) -> tuple[str, ...]:
    available = core_task_names(tasks_dir)
    if not available:
        raise RunError("no core tasks found (directories under tasks/ with checker.sh)")
    if not wanted:
        return available
    asked: list[str] = []
    for chunk in wanted:
        asked.extend(piece.strip() for piece in chunk.split(",") if piece.strip())
    missing = [name for name in asked if name not in available]
    if missing:
        raise RunError("unknown task(s): " + ", ".join(missing))
    seen: set[str] = set()
    chosen: list[str] = []
    for name in asked:
        if name not in seen:
            seen.add(name)
            chosen.append(name)
    return tuple(chosen)


def task_component(task: str) -> str:
    return task.replace("/", "__")


def cell_file(out_dir: Path, pr: str, side: str, task: str, trial: int) -> Path:
    return out_dir / pr / "cells" / side / task_component(task) / f"{trial}.json"


def read_cell(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def plan_cells(prs, tasks: tuple[str, ...], trials: int) -> list[dict]:
    cells = []
    for pr in prs:
        for side in (Side.WITHOUT, Side.WITH):
            for task in tasks:
                for trial in range(1, trials + 1):
                    cells.append({
                        "pr": pr.pr,
                        "side": side.value,
                        "sha": pr.sha_for(side),
                        "task": task,
                        "trial": trial,
                    })
    return cells


def format_plan(prs, tasks: tuple[str, ...], trials: int) -> str:
    lines = [
        f"{pr.pr} without {pr.without_sha} with {pr.with_sha}"
        for pr in prs
    ]
    lines.append("tasks: " + ",".join(tasks))
    lines.append(f"trials: {trials}")
    lines.append(f"cells: {len(prs) * 2 * len(tasks) * trials}")
    return "\n".join(lines) + "\n"


def over_budget(out_dir: Path, max_cost_usd: float | None) -> str | None:
    """Return a stop reason once finished cells pass the cap or lack tokens."""
    if max_cost_usd is None:
        return None
    spent = 0.0
    for path in out_dir.glob("*/cells/*/*/*.json"):
        row = read_cell(path)
        if row is None:
            continue
        cost = row_cost(row)
        if cost is None:
            return "unmetered tokens in a finished cell; not launching more cells"
        spent += cost
    if spent >= max_cost_usd:
        return f"estimated cost ${spent:.2f} reached the ${max_cost_usd:.2f} cap"
    return None


def project_side(out_dir: Path, pr: str, side: str) -> None:
    root = out_dir / pr / "cells" / side
    rows = []
    if root.is_dir():
        for path in sorted(root.glob("*/*.json")):
            row = read_cell(path)
            if row is not None:
                rows.append(row)
    dest = out_dir / pr / f"{side}.jsonl"
    if not rows and not dest.exists():
        return
    payload = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    publish_text(dest, payload)


def _sidecar(out_dir: Path, pr: str, side: str) -> Path:
    return out_dir / pr / f"{side}.incompatible.json"


def write_incompatible(out_dir: Path, pr: str, side: str, sha: str, reason: str) -> None:
    publish_text(_sidecar(out_dir, pr, side), json.dumps({
        "pr": pr,
        "side": side,
        "sha": sha,
        "status": "incompatible",
        "reason": reason,
    }, sort_keys=True))


def clear_incompatible(out_dir: Path, pr: str, side: str) -> None:
    path = _sidecar(out_dir, pr, side)
    if path.is_file():
        path.unlink()


def execute_cell(spec: dict) -> None:
    """Run one cell. The process environment is restored on the way out."""
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    keys = (
        "OBENCH_OPENCODE_BIN",
        "OBENCH_OPENCODE_CONFIG_JSON",
        "OBENCH_OPENCODE_PERMISSION_CONFIG",
    )
    saved = {key: os.environ.get(key) for key in keys}
    try:
        os.environ["OBENCH_OPENCODE_BIN"] = spec["binary"]
        if spec.get("config"):
            os.environ["OBENCH_OPENCODE_CONFIG_JSON"] = json.dumps(spec["config"])
        else:
            os.environ.pop("OBENCH_OPENCODE_CONFIG_JSON", None)
        os.environ["OBENCH_OPENCODE_PERMISSION_CONFIG"] = (
            "1" if spec.get("permission_config") else "0"
        )
        from obench.run import load_adapter, run_cell
        adapter = load_adapter(spec["adapters_dir"], "opencode")
        harness_version = adapter.version() if hasattr(adapter, "version") else None
        row = run_cell(
            "opencode",
            spec["task"],
            spec["model"],
            spec["trial"],
            spec["timeout_s"],
            spec["tasks_dir"],
            spec["adapters_dir"],
            CHECKER_TIMEOUT_S,
            exec_mode="local",
            harness_version=harness_version,
            version_drift=True,
        )
        publish_text(Path(spec["cell_path"]), json.dumps(row, sort_keys=True))
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _adapters_dir() -> str:
    import obench
    return str(Path(obench.__file__).resolve().parent / "adapters")


def _fill(spec: dict, prepared: dict, out_dir: Path, tasks_dir: str, adapters: str,
          model: str, timeout_s: int) -> dict:
    filled = dict(spec)
    filled.update({
        "binary": prepared["binary"],
        "config": prepared["config"],
        "permission_config": prepared["permission_config"],
        "cell_path": str(cell_file(out_dir, spec["pr"], spec["side"], spec["task"], spec["trial"])),
        "tasks_dir": tasks_dir,
        "adapters_dir": adapters,
        "model": model,
        "timeout_s": timeout_s,
    })
    return filled


def drive(prs, tasks, trials, out_dir, *, jobs, model, timeout_s, cache,
          max_cost_usd, dry_run, tasks_dir, build_fn=None, assess_fn=None,
          worker=None):
    """Build, assess, and run. Returns ``(plan_text, launched, stopped_reason)``."""
    out_dir = Path(out_dir)
    tasks = tuple(tasks)
    plan = format_plan(prs, tasks, trials)
    if dry_run:
        return plan, 0, None
    build_fn = build_fn or binary
    assess_fn = assess_fn or assess
    worker = worker or execute_cell
    tasks_dir_s = str(tasks_dir)
    adapters = _adapters_dir()
    pending = []
    for spec in plan_cells(prs, tasks, trials):
        path = cell_file(out_dir, spec["pr"], spec["side"], spec["task"], spec["trial"])
        if read_cell(path) is not None:
            project_side(out_dir, spec["pr"], spec["side"])
            continue
        pending.append(spec)
    prepared: dict[str, dict] = {}
    announced: set[tuple[str, str, str]] = set()

    def materialize(spec: dict) -> dict | None:
        sha = spec["sha"]
        if sha not in prepared:
            try:
                built = build_fn(sha, Path(cache))
            except (BuildError, OSError) as exc:
                prepared[sha] = {"ok": False, "reason": f"build failed: {exc}"}
            else:
                assessment = assess_fn(str(built))
                if assessment.status == "incompatible":
                    prepared[sha] = {"ok": False, "reason": assessment.reason}
                else:
                    prepared[sha] = {
                        "ok": True,
                        "binary": str(built),
                        "config": assessment.config,
                        "permission_config": assessment.permission_config,
                        "reason": assessment.reason,
                    }
        state = prepared[sha]
        if not state["ok"]:
            write_incompatible(out_dir, spec["pr"], spec["side"], sha, state["reason"])
            key = (spec["pr"], spec["side"], sha)
            if key not in announced:
                announced.add(key)
                print(
                    f"{spec['pr']} {spec['side']} incompatible: {state['reason']}",
                    file=sys.stderr,
                )
            return None
        clear_incompatible(out_dir, spec["pr"], spec["side"])
        return state

    launched = 0
    stopped = None

    def take(spec):
        nonlocal stopped
        if stopped:
            return None
        stopped = over_budget(out_dir, max_cost_usd)
        if stopped:
            print(stopped, file=sys.stderr)
            return None
        state = materialize(spec)
        if state is None:
            return None
        return _fill(spec, state, out_dir, tasks_dir_s, adapters, model, timeout_s)

    if jobs <= 1:
        for spec in pending:
            filled = take(spec)
            if stopped:
                break
            if filled is None:
                continue
            worker(filled)
            launched += 1
            project_side(out_dir, spec["pr"], spec["side"])
        return plan, launched, stopped

    import multiprocessing
    context = multiprocessing.get_context("spawn")
    errors = []
    with ProcessPoolExecutor(max_workers=jobs, mp_context=context) as pool:
        inflight = {}
        index = 0

        def submit_more():
            nonlocal index, stopped, launched
            while len(inflight) < jobs and index < len(pending):
                spec = pending[index]
                index += 1
                filled = take(spec)
                if stopped:
                    return
                if filled is None:
                    continue
                inflight[pool.submit(worker, filled)] = spec
                launched += 1

        submit_more()
        while inflight:
            done, _ = wait(set(inflight), return_when=FIRST_COMPLETED)
            for fut in done:
                spec = inflight.pop(fut)
                try:
                    fut.result()
                except Exception as exc:  # noqa: BLE001 - recorded, other cells finish
                    errors.append(exc)
                    stopped = stopped or f"cell failed: {exc}"
                project_side(out_dir, spec["pr"], spec["side"])
            if not errors:
                submit_more()
    if errors:
        raise errors[0]
    return plan, launched, stopped


def _tasks_dir_from_discovery() -> Path:
    roots = build_task_roots(include_imported=False)
    if not roots:
        raise RunError("no core tasks directory found")
    return Path(roots[0][1])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A/B OpenCode harness pull requests")
    parser.add_argument("prs", type=Path, help="PR list CSV or JSONL")
    parser.add_argument("--pr", action="append", default=[], help="PR id, or comma-separated ids")
    parser.add_argument("--tasks", action="append", default=[], help="task name, or comma-separated names")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--model", default="claude-opus-5-5")
    parser.add_argument("--timeout", type=int, default=2400)
    parser.add_argument("--out", type=Path, default=Path("results/ab"))
    parser.add_argument("--cache", type=Path, default=Path("results/opencode-src"))
    parser.add_argument("--max-cost-usd", type=float, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.trials < 1:
        print("error: --trials must be >= 1", file=sys.stderr)
        return 2
    if args.jobs < 1:
        print("error: --jobs must be >= 1", file=sys.stderr)
        return 2
    if args.max_cost_usd is not None and args.max_cost_usd < 0:
        print("error: --max-cost-usd must be >= 0", file=sys.stderr)
        return 2
    try:
        prs = select_prs(parse_prs(args.prs), args.pr or None)
        tasks = resolve_tasks(args.tasks or None)
        tasks_dir = _tasks_dir_from_discovery()
        plan, launched, stopped = drive(
            prs, tasks, args.trials, args.out,
            jobs=args.jobs, model=args.model, timeout_s=args.timeout,
            cache=args.cache, max_cost_usd=args.max_cost_usd, dry_run=args.dry_run,
            tasks_dir=tasks_dir,
        )
    except (PrListError, RunError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.dry_run:
        sys.stdout.write(plan)
        return 0
    print(f"launched {launched}")
    if stopped:
        print(stopped)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
