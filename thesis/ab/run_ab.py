"""Build both sides of each pull request and run the same tasks on each binary.

Cells land in their own files. The parent rewrites each side's JSONL from
those files after a cell finishes. The default model route points every
harness at one local Anthropic proxy. ``--model-route vertex`` keeps
OpenCode on the native Vertex provider. A binary that cannot load the
chosen model records ``<side>.incompatible.json`` and does not produce a
score.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path

from obench.validate_tasks import build_task_roots, discover_tasks

from thesis.ab.build_opencode import binary as build_opencode
from thesis.ab.compat import assess
from thesis.ab.durable import publish_text
from thesis.ab.errors import BuildError, Incompatible
from thesis.ab.harness import harness_name
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
                        "repo": pr.repo,
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
    harness = spec.get("harness") or "opencode"
    keys = (
        "OBENCH_OPENCODE_BIN",
        "OBENCH_OPENCODE_CONFIG_JSON",
        "OBENCH_OPENCODE_PERMISSION_CONFIG",
        "OBENCH_OPENCODE_PROXY",
        "OBENCH_PI_VERTEX",
        "OBENCH_PI_BIN",
    )
    saved = {key: os.environ.get(key) for key in keys}
    try:
        if harness == "opencode":
            os.environ["OBENCH_OPENCODE_BIN"] = spec["binary"]
            if spec.get("config"):
                os.environ["OBENCH_OPENCODE_CONFIG_JSON"] = json.dumps(spec["config"])
            else:
                os.environ.pop("OBENCH_OPENCODE_CONFIG_JSON", None)
            os.environ["OBENCH_OPENCODE_PERMISSION_CONFIG"] = (
                "1" if spec.get("permission_config") else "0"
            )
            if spec.get("proxy"):
                os.environ["OBENCH_OPENCODE_PROXY"] = json.dumps(spec["proxy"])
            else:
                os.environ.pop("OBENCH_OPENCODE_PROXY", None)
            os.environ.pop("OBENCH_PI_VERTEX", None)
            os.environ.pop("OBENCH_PI_BIN", None)
        else:
            os.environ.pop("OBENCH_OPENCODE_BIN", None)
            os.environ.pop("OBENCH_OPENCODE_CONFIG_JSON", None)
            os.environ.pop("OBENCH_OPENCODE_PERMISSION_CONFIG", None)
            os.environ.pop("OBENCH_OPENCODE_PROXY", None)
            vertex = spec.get("vertex") or {}
            os.environ["OBENCH_PI_VERTEX"] = json.dumps(vertex)
            os.environ["OBENCH_PI_BIN"] = vertex.get("bin") or spec["binary"]
        from obench.run import load_adapter, run_cell
        adapter = load_adapter(spec["adapters_dir"], harness)
        harness_version = adapter.version() if hasattr(adapter, "version") else None
        row = run_cell(
            harness,
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
        "harness": prepared.get("harness") or "opencode",
        "vertex": prepared.get("vertex"),
        "proxy": prepared.get("proxy"),
        "cell_path": str(cell_file(out_dir, spec["pr"], spec["side"], spec["task"], spec["trial"])),
        "tasks_dir": tasks_dir,
        "adapters_dir": adapters,
        "model": model,
        "timeout_s": timeout_s,
    })
    return filled


def _host_bun(cache: Path) -> str:
    found = [path for path in Path(cache).glob("bun/*/bun") if os.access(path, os.X_OK)]
    if found:
        return str(sorted(found)[-1])
    return shutil.which("bun") or ""


def _default_build(sha, cache, repo=""):
    name = harness_name(repo) if repo else "opencode"
    if name == "pi":
        from thesis.ab.build_pi import binary as build_pi
        return build_pi(sha, cache)
    if name == "omp":
        from thesis.ab.build_omp import binary as build_omp
        return build_omp(sha, cache)
    return build_opencode(sha, cache)


def _default_assess(binary_path, repo, cache, sha, proxy_url, model_route):
    name = harness_name(repo) if repo else "opencode"
    if name == "opencode":
        if model_route == "proxy":
            return assess(str(binary_path), route="proxy", proxy_url=proxy_url or "")
        return assess(str(binary_path), route="vertex")
    from thesis.ab.compat_cli import assess_cli
    root = Path(cache) / "worktrees" / name / sha.strip().lower()
    return assess_cli(str(binary_path), root, name, proxy_url)


def _needs_proxy(prs, model_route: str) -> bool:
    if model_route == "proxy":
        return True
    return any(harness_name(pr.repo) in {"pi", "omp"} for pr in prs if pr.repo)


def drive(prs, tasks, trials, out_dir, *, jobs, model, timeout_s, cache,
          max_cost_usd, dry_run, tasks_dir, build_fn=None, assess_fn=None,
          worker=None, proxy_url=None, model_route="proxy"):
    """Build, assess, and run. Returns ``(plan_text, launched, stopped_reason)``."""
    out_dir = Path(out_dir)
    tasks = tuple(tasks)
    plan = format_plan(prs, tasks, trials)
    if dry_run:
        return plan, 0, None
    own_assess = assess_fn is None
    build_fn = build_fn or _default_build
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
    prepared: dict[tuple[str, str], dict] = {}
    announced: set[tuple[str, str, str]] = set()
    server = None
    if own_assess and proxy_url is None and _needs_proxy(prs, model_route):
        from thesis.ab.vertex_anthropic_proxy import ProxyError, start_from_env
        try:
            server = start_from_env()
        except ProxyError as exc:
            raise RunError(str(exc)) from exc
        proxy_url = server.base_url

    def materialize(spec: dict) -> dict | None:
        sha = spec["sha"]
        repo = spec.get("repo") or ""
        key = (repo, sha)
        if key not in prepared:
            try:
                built = build_fn(sha, Path(cache), repo)
            except Incompatible as exc:
                prepared[key] = {"ok": False, "reason": str(exc)}
            except (BuildError, OSError) as exc:
                prepared[key] = {"ok": False, "reason": f"build failed: {exc}"}
            else:
                if own_assess:
                    assessment = _default_assess(
                        built, repo, cache, sha, proxy_url or "", model_route,
                    )
                else:
                    assessment = assess_fn(str(built))
                if assessment.status == "incompatible":
                    prepared[key] = {"ok": False, "reason": assessment.reason}
                else:
                    prepared[key] = {
                        "ok": True,
                        "binary": str(built),
                        "config": assessment.config,
                        "permission_config": assessment.permission_config,
                        "harness": harness_name(repo) if repo else assessment.harness,
                        "vertex": assessment.vertex,
                        "proxy": assessment.proxy,
                        "reason": assessment.reason,
                    }
        state = prepared[key]
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
        filled = _fill(spec, state, out_dir, tasks_dir_s, adapters, model, timeout_s)
        if filled.get("proxy"):
            proxy = dict(filled["proxy"])
            proxy.setdefault("bun", _host_bun(Path(cache)))
            filled["proxy"] = proxy
        return filled

    try:
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
    finally:
        if server is not None:
            server.close()


def _tasks_dir_from_discovery() -> Path:
    roots = build_task_roots(include_imported=False)
    if not roots:
        raise RunError("no core tasks directory found")
    return Path(roots[0][1])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A/B harness commits on the same tasks")
    parser.add_argument("prs", type=Path, help="PR list CSV or JSONL")
    parser.add_argument("--pr", action="append", default=[], help="PR id, or comma-separated ids")
    parser.add_argument("--tasks", action="append", default=[], help="task name, or comma-separated names")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--model", default="claude-opus-5-5")
    parser.add_argument(
        "--model-route",
        choices=("proxy", "vertex"),
        default="proxy",
        help="OpenCode model path. proxy is the shared Anthropic proxy. vertex is the native provider.",
    )
    parser.add_argument("--timeout", type=int, default=2400)
    parser.add_argument("--out", type=Path, default=Path("results/ab"))
    parser.add_argument("--cache", type=Path, default=None)
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
        if args.cache is not None:
            cache = args.cache
        elif any(pr.repo for pr in prs):
            cache = Path("results/harness-src")
        else:
            cache = Path("results/opencode-src")
        plan, launched, stopped = drive(
            prs, tasks, args.trials, args.out,
            jobs=args.jobs, model=args.model, timeout_s=args.timeout,
            cache=cache, max_cost_usd=args.max_cost_usd, dry_run=args.dry_run,
            tasks_dir=tasks_dir, model_route=args.model_route,
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
