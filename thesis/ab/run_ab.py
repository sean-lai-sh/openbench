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
import csv
import hashlib
import json
import os
import random
import re
import secrets
import shutil
import sys
import tempfile
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from obench.validate_tasks import build_task_roots, discover_tasks

from thesis.ab.build_opencode import binary as build_opencode
from thesis.ab.cell_fixtures import (
    CellFixtures,
    FixtureError,
    apply_context_limit,
    apply_image_modalities,
    bind_local_webfetch,
    parse_options,
)
from thesis.ab.compat import assess
from thesis.ab.durable import exclusive_lock, publish_text
from thesis.ab.errors import BuildError, Incompatible
from thesis.ab.harness import harness_name
from thesis.ab.prs import AA_SIDES, PrListError, Side, parse_prs, select_prs
from thesis.ab.sdk_pin import ai_version_for_tree, anthropic_pin_for_tree, install_alias_for_tree
from thesis.ab.summarize import billable_tokens, row_cost
from thesis.ab.toolchain import bun_requirement
from thesis.ab.vertex_anthropic_proxy import cell_ledger_path, cell_proxy_base

CHECKER_TIMEOUT_S = 120
CELL_TIMEOUT_CAP_S = 15 * 60 - 60
_METERED = (
    "tokens_input_uncached",
    "tokens_output",
    "tokens_cache_read",
    "tokens_cache_write",
)
_STREAM_RE = re.compile(
    r"Unhandled chunk type|stream-start|stream error|ProviderInitError|BunInstallFailedError|DecimalError",
    re.IGNORECASE,
)
_GUARD_SKIP = frozenset({"infra", "incompatible"})
_CACHE_VERSION_RE = re.compile(r"""CACHE_VERSION\s*=\s*["'](\d+)["']""")
# Fast provider/toolchain crashes. A clean checker failure can also finish
# in a few seconds; these strings are the deaths that are not a verdict.
_EARLY_DEATH_RE = re.compile(
    r"Unhandled chunk type|ProviderInitError|DecimalError|prepare wasm",
    re.IGNORECASE,
)
EARLY_DEATH_S = 10.0
EARLY_DEATH_CELLS = 3


class RunError(ValueError):
    pass


def core_task_names(tasks_dir: Path | None = None) -> tuple[str, ...]:
    if tasks_dir is None:
        roots = build_task_roots(include_imported=False)
    else:
        roots = [("core", str(tasks_dir))]
    return tuple(name for _tier, name, _path in discover_tasks(roots))


def is_trigger_task(name: str) -> bool:
    """Trigger copies are opt-in. The stock comparison stays the original core set."""
    return name.startswith("trig-")


def resolve_tasks(wanted: list[str] | None, tasks_dir: Path | None = None) -> tuple[str, ...]:
    available = core_task_names(tasks_dir)
    if not available:
        raise RunError("no core tasks found (directories under tasks/ with checker.sh)")
    if not wanted:
        chosen = tuple(name for name in available if not is_trigger_task(name))
        if not chosen:
            raise RunError("no core tasks found (directories under tasks/ with checker.sh)")
        return chosen
    asked: list[str] = []
    for chunk in wanted:
        asked.extend(piece.strip() for piece in chunk.split(",") if piece.strip())
    missing = [name for name in asked if name not in available]
    if missing:
        raise RunError("unknown task(s): " + ", ".join(missing))
    seen: set[str] = set()
    chosen_list: list[str] = []
    for name in asked:
        if name not in seen:
            seen.add(name)
            chosen_list.append(name)
    return tuple(chosen_list)


@dataclass(frozen=True)
class TriggerTasks:
    pr: str
    tasks: tuple[str, ...]
    status: str
    options: CellFixtures = CellFixtures()


def load_task_map(path: Path) -> dict[str, TriggerTasks]:
    """Load ``pr,task,status`` rows, plus an optional ``options`` column.

    ``task`` may list several names separated by commas. ``options`` is a
    semicolon-separated ``key=value`` list (context, fault, mode, permissions,
    global-agents, lsp, disable-tools).
    """
    path = Path(path)
    if not path.is_file():
        raise RunError(f"task map not found: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RunError(f"task map not readable: {path}: {exc}") from exc
    reader = csv.DictReader(text.splitlines())
    fields = set(reader.fieldnames or [])
    missing = {"pr", "task", "status"} - fields
    if missing:
        raise RunError(f"{path}: missing column(s): {', '.join(sorted(missing))}")
    found: dict[str, TriggerTasks] = {}
    for index, row in enumerate(reader, start=2):
        pr = str(row.get("pr") or "").strip()
        if not pr:
            raise RunError(f"{path}:{index}: missing pr")
        if pr in found:
            raise RunError(f"{path}:{index}: duplicate PR {pr}")
        status = " ".join(str(row.get("status") or "").split())
        if not status:
            raise RunError(f"{path}:{index}: missing status")
        tasks = tuple(
            piece.strip()
            for piece in str(row.get("task") or "").split(",")
            if piece.strip()
        )
        try:
            options = parse_options(str(row.get("options") or ""))
        except FixtureError as exc:
            raise RunError(f"{path}:{index}: {exc}") from exc
        found[pr] = TriggerTasks(pr=pr, tasks=tasks, status=status, options=options)
    if not found:
        raise RunError(f"{path}: no task-map rows")
    return found


def select_task_map(prs, mapping: dict[str, TriggerTasks], path: Path, explicit: bool):
    """Return ``(prs, {pr: tasks})`` for triggerable rows.

    An explicit ``--pr`` that is not triggerable is an error. A full list
    skips those rows and says so.
    """
    chosen = []
    by_pr: dict[str, tuple[str, ...]] = {}
    for pr in prs:
        row = mapping.get(pr.pr)
        if row is None:
            raise RunError(f"{pr.pr} is not listed in {path}")
        if row.status != "triggerable":
            if explicit:
                raise RunError(
                    f"{pr.pr} is {row.status} in {path}; it has no runnable trigger task"
                )
            print(f"skip {pr.pr}: {row.status}", file=sys.stderr)
            continue
        if not row.tasks:
            raise RunError(f"{pr.pr} is triggerable in {path} but names no task")
        by_pr[pr.pr] = row.tasks
        chosen.append(pr)
    if not chosen:
        raise RunError(f"{path}: no triggerable PRs to run")
    return tuple(chosen), by_pr


def restrict_mapped_tasks(prs, tasks: dict[str, tuple[str, ...]], wanted: tuple[str, ...], *, explicit: bool):
    """Keep mapped tasks that the screen named.

    PR 4204 maps to both ``trig-subagent-followup`` and ``trig-subagent-resume``.
    ``--task trig-subagent-followup`` with ``--task-map`` runs only the named
    task. An explicit ``--pr`` whose map has none of the names is an error.
    A full list skips those PRs.
    """
    wanted_set = set(wanted)
    kept_tasks: dict[str, tuple[str, ...]] = {}
    kept_prs = []
    for pr in prs:
        names = tuple(tasks.get(pr.pr) or ())
        chosen = tuple(name for name in names if name in wanted_set)
        if not chosen:
            if explicit:
                listed = ", ".join(names) or "nothing"
                raise RunError(
                    f"{pr.pr} has no mapped task in {', '.join(wanted)}; it maps to {listed}"
                )
            print(
                f"skip {pr.pr}: no mapped task in {', '.join(wanted)}",
                file=sys.stderr,
            )
            continue
        kept_tasks[pr.pr] = chosen
        kept_prs.append(pr)
    if not kept_prs:
        raise RunError("task filter matches no trigger task")
    return tuple(kept_prs), kept_tasks


def tasks_for(tasks, pr: str) -> tuple[str, ...]:
    if isinstance(tasks, dict):
        chosen = tasks.get(pr)
        if not chosen:
            raise RunError(f"no tasks for {pr}")
        return tuple(chosen)
    return tuple(tasks)


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


def _fixture_suffix(fixtures, pr: str) -> str:
    if not fixtures:
        return ""
    options = fixtures.get(pr)
    if options is None:
        return ""
    text = options.as_text() if isinstance(options, CellFixtures) else ""
    if not text:
        return ""
    return " options " + text


def _cell_arms(*, aa: bool, with_aa: bool) -> tuple[tuple[str, str, bool], ...]:
    """``(side, arm, use_merge_sha)`` in side-major order."""
    if aa and with_aa:
        raise RunError("pass either --aa or --with-aa")
    if with_aa:
        return (
            (Side.WITHOUT.value, "ab", False),
            (Side.WITH.value, "ab", True),
            (AA_SIDES[0], "parent-vs-parent", False),
            (AA_SIDES[1], "parent-vs-parent", False),
        )
    if aa:
        return tuple((label, "parent-vs-parent", False) for label in AA_SIDES)
    return (
        (Side.WITHOUT.value, "ab", False),
        (Side.WITH.value, "ab", True),
    )


def plan_cells(prs, tasks, trials: int, *, aa: bool = False, fixtures=None,
               with_aa: bool = False) -> list[dict]:
    cells = []
    arms = _cell_arms(aa=aa, with_aa=with_aa)
    for pr in prs:
        chosen = tasks_for(tasks, pr.pr)
        payload = {}
        if fixtures and pr.pr in fixtures:
            options = fixtures[pr.pr]
            if isinstance(options, CellFixtures):
                payload = options.payload()
        for label, arm, use_merge in arms:
            sha = pr.with_sha if use_merge else pr.without_sha
            for task in chosen:
                for trial in range(1, trials + 1):
                    cell = {
                        "pr": pr.pr,
                        "repo": pr.repo,
                        "side": label,
                        "sha": sha,
                        "task": task,
                        "trial": trial,
                        "arm": arm,
                    }
                    if payload:
                        cell["fixtures"] = payload
                    cells.append(cell)
    return cells


def _trial_blocks(cells: list[dict]) -> list[list[dict]]:
    """Group cells that share one PR, task, and trial. Trial is the outer key."""
    grouped: dict[tuple, list[dict]] = {}
    pr_order: list[str] = []
    for cell in cells:
        pr = str(cell.get("pr"))
        if pr not in pr_order:
            pr_order.append(pr)
        key = (pr, int(cell.get("trial") or 0), str(cell.get("task")))
        grouped.setdefault(key, []).append(cell)
    pr_index = {pr: index for index, pr in enumerate(pr_order)}
    keys = sorted(grouped, key=lambda key: (pr_index[key[0]], key[1], key[2]))
    return [grouped[key] for key in keys]


def cell_random_seed(run_seed: int, cell: dict) -> int:
    """Stable per-cell seed. It does not depend on launch order."""
    text = "|".join([
        str(int(run_seed)),
        str(cell.get("pr") or ""),
        str(cell.get("side") or ""),
        str(cell.get("task") or ""),
        str(cell.get("trial") or ""),
    ])
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def order_cells(cells: list[dict], *, order: str = "sides", seed: int | None = None) -> list[dict]:
    """Launch order. Each cell gets ``schedule_index`` from 0.

    ``sides`` keeps the historical order: every cell of side A, then side B.
    ``interleave`` keeps both sides of one trial together, A then B. A seed
    does not change that order. ``random`` shuffles inside each trial block
    with ``random.Random(seed)``. A trial block is one PR, one task, and one
    trial number. When ``seed`` is set, each cell also records ``run_seed``
    and a derived ``cell_seed`` for per-cell randomness such as the webfetch
    colour.
    """
    if order not in {"sides", "interleave", "random"}:
        raise RunError(f"unknown order {order!r}")
    if order == "random" and seed is None:
        raise RunError("random order requires a seed")
    if order == "sides":
        ordered = [dict(cell) for cell in cells]
    else:
        rng = random.Random(seed) if order == "random" else None
        ordered = []
        for block in _trial_blocks(cells):
            group = [dict(cell) for cell in block]
            if rng is not None:
                rng.shuffle(group)
            ordered.extend(group)
    for index, cell in enumerate(ordered):
        cell["schedule_index"] = index
        if seed is not None:
            cell["run_seed"] = int(seed)
            cell["cell_seed"] = cell_random_seed(seed, cell)
    return ordered


def format_plan(prs, tasks, trials: int, *, aa: bool = False, fixtures=None,
                with_aa: bool = False, order: str = "sides", seed: int | None = None) -> str:
    lines = []
    arms = _cell_arms(aa=aa, with_aa=with_aa)
    for pr in prs:
        chosen = ",".join(tasks_for(tasks, pr.pr))
        suffix = _fixture_suffix(fixtures, pr.pr)
        if with_aa:
            lines.append(
                f"{pr.pr} without {pr.without_sha} with {pr.with_sha} "
                f"parent {pr.without_sha} sides without,with,{','.join(AA_SIDES)} "
                f"tasks {chosen}{suffix}"
            )
        elif aa:
            lines.append(
                f"{pr.pr} parent-vs-parent {pr.without_sha} "
                f"sides {','.join(AA_SIDES)} tasks {chosen}{suffix}"
            )
        elif isinstance(tasks, dict):
            lines.append(
                f"{pr.pr} without {pr.without_sha} with {pr.with_sha} tasks {chosen}{suffix}"
            )
        else:
            lines.append(f"{pr.pr} without {pr.without_sha} with {pr.with_sha}{suffix}")
    if isinstance(tasks, dict):
        lines.append("tasks: per-pr")
    else:
        lines.append("tasks: " + ",".join(tasks))
    lines.append(f"trials: {trials}")
    cell_count = sum(len(arms) * len(tasks_for(tasks, pr.pr)) * trials for pr in prs)
    lines.append(f"cells: {cell_count}")
    if seed is not None:
        lines.append(f"order: {order} seed={seed}")
    else:
        lines.append(f"order: {order}")
    if with_aa:
        lines.append("arm: ab+aa")
    elif aa:
        lines.append("arm: parent-vs-parent")
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
        if row.get("failure_class") in _GUARD_SKIP:
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
            if row is not None and row.get("failure_class") != "incompatible":
                rows.append(row)
    dest = out_dir / pr / f"{side}.jsonl"
    if not rows and not dest.exists():
        return
    payload = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    publish_text(dest, payload)


def _sidecar(out_dir: Path, pr: str, side: str, kind: str = "incompatible") -> Path:
    return out_dir / pr / f"{side}.{kind}.json"


def _write_verdict(out_dir: Path, pr: str, side: str, sha: str, status: str, reason: str) -> None:
    publish_text(_sidecar(out_dir, pr, side, status), json.dumps({
        "pr": pr,
        "side": side,
        "sha": sha,
        "status": status,
        "reason": reason,
    }, sort_keys=True))


def write_incompatible(out_dir: Path, pr: str, side: str, sha: str, reason: str) -> None:
    _write_verdict(out_dir, pr, side, sha, "incompatible", reason)


def write_infra(out_dir: Path, pr: str, side: str, sha: str, reason: str) -> None:
    _write_verdict(out_dir, pr, side, sha, "infra", reason)


def clear_incompatible(out_dir: Path, pr: str, side: str) -> None:
    for kind in ("incompatible", "infra"):
        path = _sidecar(out_dir, pr, side, kind)
        if path.is_file():
            path.unlink()


def _record_stopped(out_dir: Path, spec: dict, state: dict) -> None:
    reason = state["reason"]
    if state.get("status") == "infra":
        write_infra(out_dir, spec["pr"], spec["side"], spec["sha"], reason)
    else:
        write_incompatible(out_dir, spec["pr"], spec["side"], spec["sha"], reason)


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
        "OBENCH_OPENCODE_EVIDENCE_DIR",
        "OBENCH_OPENCODE_MODE",
        "OBENCH_OPENCODE_PERMISSIONS",
        "OBENCH_OPENCODE_GLOBAL_AGENTS",
        "OBENCH_OPENCODE_LSP",
        "OBENCH_OPENCODE_BUN",
        "OBENCH_OPENCODE_WEBFETCH_URL",
        "OBENCH_OPENCODE_OUTSIDE_PATH",
        "OBENCH_FINAL_ANSWER",
        "TMPDIR",
        "TMP",
        "TEMP",
        "OBENCH_WEBFETCH_COLOUR",
        "OBENCH_WEBFETCH_SEED",
        "OBENCH_OPENCODE_DISABLE_TOOLS",
        "OBENCH_NO_PROGRESS_S",
        "OBENCH_CELL_LEDGER",
        "OBENCH_PI_VERTEX",
        "OBENCH_PI_BIN",
    )
    saved = {key: os.environ.get(key) for key in keys}
    png_server = None
    evidence = ""
    started_at = datetime.now(timezone.utc).isoformat()
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
            fixtures = spec.get("fixtures") if isinstance(spec.get("fixtures"), dict) else {}
            mode = str(fixtures.get("mode") or "").strip()
            if mode:
                os.environ["OBENCH_OPENCODE_MODE"] = mode
            else:
                os.environ.pop("OBENCH_OPENCODE_MODE", None)
            permissions = str(fixtures.get("permissions") or "").strip()
            if permissions:
                os.environ["OBENCH_OPENCODE_PERMISSIONS"] = permissions
            else:
                os.environ.pop("OBENCH_OPENCODE_PERMISSIONS", None)
            if fixtures.get("global_agents"):
                os.environ["OBENCH_OPENCODE_GLOBAL_AGENTS"] = "1"
            else:
                os.environ.pop("OBENCH_OPENCODE_GLOBAL_AGENTS", None)
            lsp = fixtures.get("lsp") or []
            if isinstance(lsp, str):
                lsp = [lsp]
            lsp_text = ",".join(str(name).strip() for name in lsp if str(name).strip())
            if lsp_text:
                os.environ["OBENCH_OPENCODE_LSP"] = lsp_text
            else:
                os.environ.pop("OBENCH_OPENCODE_LSP", None)
            disabled = fixtures.get("disable_tools") or []
            if isinstance(disabled, str):
                disabled = disabled.split(",")
            disabled_text = ",".join(
                str(name).strip() for name in disabled if str(name).strip()
            )
            if disabled_text:
                os.environ["OBENCH_OPENCODE_DISABLE_TOOLS"] = disabled_text
            else:
                os.environ.pop("OBENCH_OPENCODE_DISABLE_TOOLS", None)
            bun = ""
            proxy = spec.get("proxy")
            if isinstance(proxy, dict):
                bun = str(proxy.get("bun") or "").strip()
            if bun:
                os.environ["OBENCH_OPENCODE_BUN"] = bun
            else:
                os.environ.pop("OBENCH_OPENCODE_BUN", None)
            raw_cell_seed = spec.get("cell_seed")
            cell_seed = (
                raw_cell_seed
                if isinstance(raw_cell_seed, int) and not isinstance(raw_cell_seed, bool)
                else None
            )
            png_server = bind_local_webfetch(os.environ, fixtures, cell_seed)
            outside = _cell_outside_path(spec)
            if outside:
                os.environ["OBENCH_OPENCODE_OUTSIDE_PATH"] = outside
            else:
                os.environ.pop("OBENCH_OPENCODE_OUTSIDE_PATH", None)
            for key, value in scratch_env(spec).items():
                os.environ[key] = value
            evidence = str(spec.get("evidence_dir") or "").strip()
            if evidence:
                evidence = str(Path(evidence).resolve())
                os.environ["OBENCH_OPENCODE_EVIDENCE_DIR"] = evidence
            else:
                os.environ.pop("OBENCH_OPENCODE_EVIDENCE_DIR", None)
            limit = spec.get("no_progress_s")
            if isinstance(limit, (int, float)) and not isinstance(limit, bool) and limit > 0:
                os.environ["OBENCH_NO_PROGRESS_S"] = str(limit)
            else:
                os.environ.pop("OBENCH_NO_PROGRESS_S", None)
            cell_ledger = str(spec.get("cell_ledger") or "").strip()
            if cell_ledger:
                os.environ["OBENCH_CELL_LEDGER"] = cell_ledger
            else:
                os.environ.pop("OBENCH_CELL_LEDGER", None)
            os.environ.pop("OBENCH_PI_VERTEX", None)
            os.environ.pop("OBENCH_PI_BIN", None)
        else:
            os.environ.pop("OBENCH_OPENCODE_BIN", None)
            os.environ.pop("OBENCH_OPENCODE_CONFIG_JSON", None)
            os.environ.pop("OBENCH_OPENCODE_PERMISSION_CONFIG", None)
            os.environ.pop("OBENCH_OPENCODE_PROXY", None)
            os.environ.pop("OBENCH_OPENCODE_EVIDENCE_DIR", None)
            os.environ.pop("OBENCH_OPENCODE_MODE", None)
            os.environ.pop("OBENCH_OPENCODE_PERMISSIONS", None)
            os.environ.pop("OBENCH_OPENCODE_GLOBAL_AGENTS", None)
            os.environ.pop("OBENCH_OPENCODE_LSP", None)
            os.environ.pop("OBENCH_OPENCODE_BUN", None)
            os.environ.pop("OBENCH_OPENCODE_WEBFETCH_URL", None)
            os.environ.pop("OBENCH_OPENCODE_OUTSIDE_PATH", None)
            os.environ.pop("OBENCH_FINAL_ANSWER", None)
            os.environ.pop("OBENCH_WEBFETCH_COLOUR", None)
            os.environ.pop("OBENCH_WEBFETCH_SEED", None)
            os.environ.pop("OBENCH_OPENCODE_DISABLE_TOOLS", None)
            os.environ.pop("OBENCH_NO_PROGRESS_S", None)
            os.environ.pop("OBENCH_CELL_LEDGER", None)
            vertex = spec.get("vertex") or {}
            os.environ["OBENCH_PI_VERTEX"] = json.dumps(vertex)
            os.environ["OBENCH_PI_BIN"] = vertex.get("bin") or spec["binary"]
        from obench.run import load_adapter, run_cell
        adapter = load_adapter(spec["adapters_dir"], harness)
        harness_version = adapter.version() if hasattr(adapter, "version") else None
        transcripts_dir = str(spec.get("transcripts_dir") or "").strip() or None
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
            transcripts_dir=transcripts_dir,
            results_stem=str(spec.get("side") or ""),
        )
        installed = row.pop("installed_anthropic", None) if isinstance(row, dict) else None
        installed_text = installed if isinstance(installed, str) else None
        if isinstance(row, dict):
            apply_cell_meter(row, spec.get("proxy"))
            attach_schedule(row, spec, started_at)
            from thesis.ab.evidence import attach_cell_metrics
            attach_cell_metrics(row, evidence if evidence else None)
            if spec.get("task") == "trig-tmpdir":
                scratch = os.environ.get("TMPDIR", "").strip()
                if scratch:
                    names = leaked_temp_dir_names(scratch)
                    row["tmpdir_leaked_dirs"] = len(names)
                    row["tmpdir_leaked_names"] = names
                    if evidence:
                        evidence_path = Path(evidence)
                        evidence_path.mkdir(parents=True, exist_ok=True)
                        publish_text(evidence_path / "scratch-tmpdir.txt", scratch + "\n")
            from thesis.ab.watch import apply_watchdog_class
            apply_watchdog_class(row)
            if png_server is not None:
                row["webfetch_seed"] = png_server.seed
                row["webfetch_colour"] = png_server.colour
        apply_toolchain(row, spec.get("toolchain"), installed_text)
        toolchain_path = spec.get("toolchain_path")
        if toolchain_path:
            publish_side_toolchain(Path(toolchain_path), spec.get("toolchain"), installed_text)
        publish_text(Path(spec["cell_path"]), json.dumps(row, sort_keys=True))
    finally:
        if png_server is not None:
            png_server.close()
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _adapters_dir() -> str:
    import obench
    return str(Path(obench.__file__).resolve().parent / "adapters")


def cell_transcripts_dir(out_dir: Path, pr: str, transcripts_root: Path | None = None) -> Path:
    """Directory passed to ``run_cell`` for one PR's local transcripts."""
    if transcripts_root is not None:
        return Path(transcripts_root) / pr / "transcripts"
    return Path(out_dir) / pr / "transcripts"


def _absolute(path: Path | str) -> str:
    return str(Path(path).resolve())


def _cell_scratch_tmpdir(spec: dict) -> str | None:
    """A private temp root for PR 25226 so cells do not share ``/tmp/opencode``.

    OpenCode whitelists ``<os.tmpdir()>/opencode``. Setting ``TMPDIR`` makes
    that directory ``/tmp/obench-tmp-<token>/opencode`` for this cell only.
    """
    if spec.get("task") != "trig-tmpdir":
        return None
    token = secrets.token_hex(8)
    directory = Path("/tmp") / f"obench-tmp-{token}"
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True, mode=0o700)
    ensure_empty_opencode(directory)
    return str(directory)


def ensure_empty_opencode(root: Path) -> Path:
    """Create ``<root>/opencode`` with nothing in it.

    OpenCode whitelists that directory. A leftover file from another cell
    would look like this cell's own scratch.
    """
    opencode = Path(root) / "opencode"
    if opencode.exists():
        shutil.rmtree(opencode)
    opencode.mkdir(mode=0o700)
    return opencode


# The runner creates ``<root>/opencode`` empty so OpenCode's whitelist has a
# directory. Anything else under the per-cell temp root was created by the agent.
_RUNNER_TEMP_DIRS = frozenset({"opencode"})


def leaked_temp_dir_names(root: str | Path) -> list[str]:
    """Relative directory names the agent left under the per-cell temp root.

    Includes ``tmp.*`` siblings of ``opencode`` and directories inside
    ``opencode``. The runner-created ``opencode`` directory itself is not a
    leak. Names are sorted and use forward slashes.
    """
    root = Path(root)
    if not root.is_dir():
        return []
    names = []
    for path in root.rglob("*"):
        if not path.is_dir():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in _RUNNER_TEMP_DIRS:
            continue
        names.append(relative)
    return sorted(names)


def leaked_temp_dirs(root: str | Path) -> int:
    """How many agent-created directories remain under the per-cell temp root."""
    return len(leaked_temp_dir_names(root))


def scratch_env(spec: dict) -> dict[str, str]:
    """Environment that points this cell's temp directory at its own root."""
    path = _cell_scratch_tmpdir(spec)
    if not path:
        return {}
    return {"TMPDIR": path, "TMP": path, "TEMP": path}


def _cell_outside_path(spec: dict) -> str | None:
    """A clean per-cell path for the outside-file task. Nothing is left shared."""
    if spec.get("task") != "trig-lsp-outside":
        return None
    token = secrets.token_hex(8)
    directory = Path("/tmp") / f"obench-shared-{token}"
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True, mode=0o700)
    return str(directory / "greeter_copy.py")


def cell_evidence_dir(transcripts_dir: Path, side: str, task: str, trial: int) -> Path:
    """Per-cell directory for OpenCode session storage and logs."""
    return Path(transcripts_dir) / side / task_component(task) / str(trial)


def _fill(spec: dict, prepared: dict, out_dir: Path, tasks_dir: str, adapters: str,
          model: str, timeout_s: int, transcripts_root: Path | None = None,
          no_progress_s: float = 0) -> dict:
    transcripts = cell_transcripts_dir(out_dir, spec["pr"], transcripts_root)
    filled = dict(spec)
    filled.update({
        "binary": prepared["binary"],
        "config": prepared["config"],
        "permission_config": prepared["permission_config"],
        "harness": prepared.get("harness") or "opencode",
        "vertex": prepared.get("vertex"),
        "proxy": prepared.get("proxy"),
        "cell_path": _absolute(cell_file(out_dir, spec["pr"], spec["side"], spec["task"], spec["trial"])),
        "tasks_dir": tasks_dir,
        "adapters_dir": adapters,
        "model": model,
        "timeout_s": cell_timeout(timeout_s),
        "toolchain": prepared.get("toolchain") or {},
        "toolchain_path": _absolute(out_dir / spec["pr"] / f"{spec['side']}.toolchain.json"),
        "transcripts_dir": _absolute(transcripts),
        "evidence_dir": _absolute(cell_evidence_dir(
            transcripts, spec["side"], spec["task"], spec["trial"],
        )),
    })
    if (
        isinstance(no_progress_s, (int, float))
        and not isinstance(no_progress_s, bool)
        and no_progress_s > 0
    ):
        filled["no_progress_s"] = float(no_progress_s)
    fixtures = filled.get("fixtures") if isinstance(filled.get("fixtures"), dict) else {}
    config = filled.get("config") or {}
    changed = False
    context = fixtures.get("context")
    if isinstance(context, int) and context > 0:
        config = apply_context_limit(config, context)
        changed = True
    if fixtures.get("modalities") == "image":
        config = apply_image_modalities(config)
        changed = True
    if changed:
        filled["config"] = config
    return filled


def cell_timeout(requested: int) -> int:
    if requested < 1:
        return requested
    return min(int(requested), CELL_TIMEOUT_CAP_S)


def apply_toolchain(row: dict, toolchain: dict | None, installed: str | None = None) -> dict:
    body = {}
    if isinstance(toolchain, dict):
        for key in ("ai", "anthropic", "bun"):
            value = toolchain.get(key)
            if isinstance(value, str) and value.strip():
                body[key] = value.strip()
    if isinstance(installed, str) and installed.strip():
        body["anthropic"] = installed.strip()
    if body:
        row["toolchain"] = body
    return body


def write_toolchain(out_dir: Path, pr: str, side: str, toolchain: dict | None) -> None:
    publish_side_toolchain(out_dir / pr / f"{side}.toolchain.json", toolchain)


def _read_toolchain_file(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return apply_toolchain({}, parsed if isinstance(parsed, dict) else None)


def publish_side_toolchain(path: Path, toolchain: dict | None, installed: str | None = None) -> None:
    incoming = apply_toolchain({}, toolchain)
    installed_text = installed.strip() if isinstance(installed, str) else ""
    if not incoming and not installed_text:
        return
    path = Path(path)
    with exclusive_lock(path.parent / "locks" / f"{path.name}.lock"):
        current = _read_toolchain_file(path)
        merged = dict(current)
        for key in ("ai", "bun"):
            if incoming.get(key) and not merged.get(key):
                merged[key] = incoming[key]
        if installed_text:
            merged["anthropic"] = installed_text
        elif incoming.get("anthropic") and not merged.get("anthropic"):
            merged["anthropic"] = incoming["anthropic"]
        if not merged or merged == current:
            return
        publish_text(path, json.dumps(merged, sort_keys=True))


def toolchain_for_checkout(checkout: Path) -> dict:
    body = {}
    try:
        bun = bun_requirement(checkout).split("+", 1)[0].strip()
    except BuildError:
        bun = ""
    if bun:
        body["bun"] = bun
    ai = ai_version_for_tree(checkout)
    if ai:
        body["ai"] = ai
    pin = anthropic_pin_for_tree(checkout)
    if pin:
        body["anthropic"] = pin
    return body


def bun_for_checkout(cache: Path, checkout: Path) -> Path:
    cache = Path(cache).resolve()
    version = bun_requirement(checkout).split("+", 1)[0].strip()
    return (cache / "bun" / version / "bun").resolve()


def zero_metered(row: dict) -> bool:
    for field in _METERED:
        value = row.get(field)
        if isinstance(value, bool):
            return False
        if isinstance(value, (int, float)) and value > 0:
            return False
    split = billable_tokens(row)
    if split and any(value > 0 for value in split.values()):
        return False
    return True


def attach_schedule(row: dict, spec: dict, started_at: str) -> None:
    """Record where this cell sat in the launch schedule and when it started."""
    if not isinstance(row, dict):
        return
    index = spec.get("schedule_index")
    if isinstance(index, int) and not isinstance(index, bool):
        row["schedule_index"] = index
    for key in ("run_seed", "cell_seed"):
        value = spec.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            row[key] = value
    if started_at:
        row["started_at"] = started_at


def expose_request_totals(row: dict) -> dict:
    """Publish every proxy request and keep the main session under other names.

    The ledger is every model request for this cell, including subagent and
    child sessions that reused the cell base URL. ``requests_*`` and the
    ``tokens_*`` split become that total. The harness main-session split is
    kept as ``tokens_main_*`` and ``token_basis_main``.
    """
    if row.get("token_basis_proxy") != "proxy_measured":
        return row
    pairs = (
        ("tokens_input_uncached", "tokens_proxy_input_uncached", "requests_input_uncached",
         "tokens_main_input_uncached"),
        ("tokens_output", "tokens_proxy_output", "requests_output", "tokens_main_output"),
        ("tokens_cache_read", "tokens_proxy_cache_read", "requests_cache_read",
         "tokens_main_cache_read"),
        ("tokens_cache_write", "tokens_proxy_cache_write", "requests_cache_write",
         "tokens_main_cache_write"),
    )
    split: dict[str, int | float] = {}
    for name, proxy_name, _request_name, _main_name in pairs:
        value = row.get(proxy_name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return row
        split[name] = int(value) if float(value).is_integer() else float(value)
    calls = row.get("tokens_proxy_calls")
    if isinstance(calls, bool) or not isinstance(calls, (int, float)):
        return row
    basis = row.get("token_basis")
    if basis not in (None, "proxy_measured"):
        for name, _proxy_name, _request_name, main_name in pairs:
            if main_name not in row and name in row:
                row[main_name] = row[name]
        raw = row.get("usage_raw")
        if isinstance(raw, list) and "tokens_main_calls" not in row:
            row["tokens_main_calls"] = len(raw)
        if "token_basis_main" not in row and isinstance(basis, str) and basis:
            row["token_basis_main"] = basis
    for name, _proxy_name, request_name, _main_name in pairs:
        row[name] = split[name]
        row[request_name] = split[name]
    row["requests_count"] = int(calls)
    fresh = split["tokens_input_uncached"] + split["tokens_output"]
    row["tokens"] = int(fresh) if float(fresh).is_integer() else fresh
    row["token_basis"] = "proxy_measured"
    cost = row_cost(row)
    if cost is not None:
        row["requests_cost_usd"] = cost
    return row


def promote_proxy_meter(row: dict) -> dict:
    if row.get("token_basis_proxy") != "proxy_measured":
        return row
    if any(
        isinstance(row.get(field), (int, float)) and not isinstance(row.get(field), bool) and row.get(field) > 0
        for field in _METERED
    ):
        return row
    split = billable_tokens(row)
    if split is None or not any(value > 0 for value in split.values()):
        return row
    for field in _METERED:
        value = split[field]
        row[field] = int(value) if float(value).is_integer() else value
    if row.get("tokens") is None:
        fresh = split["tokens_input_uncached"] + split["tokens_output"]
        row["tokens"] = int(fresh) if float(fresh).is_integer() else fresh
    if not row.get("token_basis"):
        row["token_basis"] = "proxy_measured"
    return row


def apply_cell_meter(row: dict, proxy: dict | None) -> dict:
    if not isinstance(row, dict) or not isinstance(proxy, dict):
        return row
    ledger = proxy.get("ledger_dir")
    cell = proxy.get("cell_id")
    if not ledger or not cell:
        return row
    from obench.run import apply_proxy_ledger, read_proxy_ledger
    from thesis.ab.vertex_anthropic_proxy import faults_served
    row["faults_served"] = faults_served(str(ledger), str(cell))
    records = read_proxy_ledger(str(ledger), str(cell))
    if not records:
        return row
    apply_proxy_ledger(row, records)
    expose_request_totals(row)
    promote_proxy_meter(row)
    if row.get("usage_raw") is None:
        usages = [
            record.get("usage")
            for record in records
            if isinstance(record, dict) and isinstance(record.get("usage"), dict)
        ]
        if usages:
            row["usage_raw"] = usages
    return row


def bind_cell_proxy(filled: dict, ledger_dir: Path) -> dict:
    proxy = filled.get("proxy")
    if not isinstance(proxy, dict):
        return filled
    base = str(proxy.get("base_url") or "")
    if not base:
        return filled
    cell_id = secrets.token_hex(8)
    rewritten = cell_proxy_base(base, cell_id)
    filled = dict(filled)
    proxy = dict(proxy)
    config = filled.get("config")
    if isinstance(config, dict):
        filled["config"] = json.loads(json.dumps(config).replace(base, rewritten))
    proxy["base_url"] = rewritten
    proxy["cell_id"] = cell_id
    proxy["ledger_dir"] = str(ledger_dir)
    filled["proxy"] = proxy
    filled["cell_ledger"] = str(cell_ledger_path(Path(ledger_dir), cell_id))
    return filled


_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_DRAWING_RE = re.compile(r"[\u2500-\u259f]")


def _readable_tail(text: str) -> str:
    """Drop the OpenCode banner so an incompatible reason stays one line."""
    cleaned = _DRAWING_RE.sub(" ", _ANSI_RE.sub("", text))
    return " ".join(cleaned.split())


def preflight_stop_reason(row: dict | None) -> str | None:
    if isinstance(row, dict):
        drift = row.get("sdk_drift")
        if isinstance(drift, str) and drift.strip():
            return drift.strip()
    reason = provider_stream_failure(row)
    if reason:
        return reason
    if not isinstance(row, dict) or row.get("completed") or not zero_metered(row):
        return None
    err = str(row.get("error") or "")
    if not re.fullmatch(r"exit \d+", err):
        return None
    tail = _readable_tail(str(row.get("output_tail") or ""))
    detail = f"{err}: {tail[:180]}" if tail else err
    return f"preflight exited before any metered call: {detail}"


def provider_stream_failure(row: dict | None) -> str | None:
    if not isinstance(row, dict) or not zero_metered(row):
        return None
    text = "\n".join(str(row.get(key) or "") for key in ("error", "output_tail", "full_output"))
    match = _STREAM_RE.search(text)
    if match is None:
        return None
    line = next((item.strip() for item in text.splitlines() if _STREAM_RE.search(item)), match.group(0))
    return f"provider stream error with no metered tokens: {line[:180]}"


def _side_key(spec: dict) -> tuple[str, str]:
    return (spec.get("repo") or "", spec["sha"])


def _side_has_metered_work(out_dir: Path, spec: dict, ignore: Path) -> bool:
    root = out_dir / spec["pr"] / "cells" / spec["side"]
    if not root.is_dir():
        return False
    ignored = ignore.resolve()
    for path in root.glob("*/*.json"):
        if path.resolve() == ignored:
            continue
        row = read_cell(path)
        if row and row.get("failure_class") != "incompatible" and not zero_metered(row):
            return True
    return False


def _finished_rows(out_dir: Path, spec: dict) -> list[dict]:
    root = out_dir / spec["pr"] / "cells" / spec["side"]
    if not root.is_dir():
        return []
    rows = []
    for path in sorted(root.glob("*/*.json")):
        row = read_cell(path)
        if row is not None:
            rows.append(row)
    return rows


def unmetered_side(rows: list[dict]) -> str | None:
    if len(rows) < 2 or any(not zero_metered(row) for row in rows):
        return None
    return "finished cells have no metered tokens"


def _cell_runtime_s(row: dict) -> float | None:
    for key in ("t_agent_s", "wall_time_s"):
        value = row.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if value >= 0:
            return float(value)
    return None


def early_death_marker(row: dict | None) -> str | None:
    """Return the crash signature when a cell died in under 10 seconds.

    ``incompatible`` rows are left alone: a zero-token stream error already
    stops the side. A passing checker is not a death.
    """
    if not isinstance(row, dict) or row.get("success") is True:
        return None
    if row.get("failure_class") == "incompatible":
        return None
    runtime = _cell_runtime_s(row)
    if runtime is None or runtime >= EARLY_DEATH_S:
        return None
    text = "\n".join(
        str(row.get(key) or "")
        for key in ("error", "output_tail", "full_output")
    )
    match = _EARLY_DEATH_RE.search(text)
    if match is None:
        return None
    return match.group(0)


def _reclassify_early_deaths(out_dir: Path, spec: dict) -> None:
    root = out_dir / spec["pr"] / "cells" / spec["side"]
    if not root.is_dir():
        return
    for path in sorted(root.glob("*/*.json")):
        row = read_cell(path)
        marker = early_death_marker(row)
        if marker is None or not isinstance(row, dict):
            continue
        reason = f"early death under 10s: {marker}"
        if row.get("failure_class") == "infra" and row.get("failure_reason") == reason:
            continue
        row["failure_class"] = "infra"
        row["failure_reason"] = reason
        row["success"] = False
        row["score"] = 0.0
        publish_text(path, json.dumps(row, sort_keys=True))


def _ordered_side_rows(rows: list[dict]) -> list[dict]:
    if rows and all(isinstance(row.get("ts_iso"), str) and row.get("ts_iso") for row in rows):
        return sorted(rows, key=lambda row: str(row["ts_iso"]))
    return list(rows)


def early_death_side(rows: list[dict]) -> str | None:
    """Stop a side once its first three cells are fast provider crashes.

    One fast crash is infra and is not scored. Three in a row means the
    binary will keep dying the same way, so the remaining trials are not launched.
    """
    ordered = _ordered_side_rows(rows)
    if len(ordered) < EARLY_DEATH_CELLS:
        return None
    head = ordered[:EARLY_DEATH_CELLS]
    if any(early_death_marker(row) is None for row in head):
        return None
    return "first cells died in under 10s"


def _absorb_finished(spec: dict, out_dir: Path, prepared: dict) -> None:
    path = cell_file(out_dir, spec["pr"], spec["side"], spec["task"], spec["trial"])
    row = read_cell(path)
    reason = provider_stream_failure(row)
    if reason and isinstance(row, dict):
        row["failure_class"] = "incompatible"
        row["failure_reason"] = reason
        publish_text(path, json.dumps(row, sort_keys=True))
        if not _side_has_metered_work(out_dir, spec, path):
            write_incompatible(out_dir, spec["pr"], spec["side"], spec["sha"], reason)
            prepared[_side_key(spec)] = {"ok": False, "reason": reason}
    elif prepared.get(_side_key(spec), {}).get("ok", True):
        infra_reason = unmetered_side(_finished_rows(out_dir, spec))
        if infra_reason:
            write_infra(out_dir, spec["pr"], spec["side"], spec["sha"], infra_reason)
            prepared[_side_key(spec)] = {
                "ok": False,
                "reason": infra_reason,
                "status": "infra",
            }
    _reclassify_early_deaths(out_dir, spec)
    if prepared.get(_side_key(spec), {}).get("ok", True):
        death = early_death_side(_finished_rows(out_dir, spec))
        if death:
            write_infra(out_dir, spec["pr"], spec["side"], spec["sha"], death)
            prepared[_side_key(spec)] = {
                "ok": False,
                "reason": death,
                "status": "infra",
            }
    project_side(out_dir, spec["pr"], spec["side"])


def cache_version_for_checkout(checkout: Path) -> str:
    """Return CACHE_VERSION from the checkout, or "" when the tree has none."""
    path = Path(checkout) / "packages" / "opencode" / "src" / "global" / "index.ts"
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    match = _CACHE_VERSION_RE.search(text)
    return match.group(1) if match else ""


def _decorate_toolchain(state: dict, cache: Path, sha: str, repo: str) -> tuple[dict, str | None]:
    proxy = state.get("proxy")
    if not isinstance(proxy, dict):
        return state, None
    harness = state.get("harness") or "opencode"
    if harness != "opencode":
        return state, None
    checkout = Path(cache) / "worktrees" / sha.strip().lower()
    if not (checkout / "package.json").is_file():
        return state, None
    proxy = dict(proxy)
    try:
        bun = bun_for_checkout(cache, checkout)
    except BuildError as exc:
        return state, f"bun: {exc}"
    if bun.is_file():
        proxy["bun"] = str(bun)
    pin = anthropic_pin_for_tree(checkout)
    if pin:
        proxy["anthropic_sdk"] = pin
    proxy["sdk_install_alias"] = install_alias_for_tree(checkout)
    cache_version = cache_version_for_checkout(checkout)
    if cache_version:
        proxy["cache_version"] = cache_version
    state = dict(state)
    state["proxy"] = proxy
    state["toolchain"] = toolchain_for_checkout(checkout)
    if not pin and proxy.get("needs_sdk"):
        return state, "no @ai-sdk/anthropic release matches this build's ai package"
    return state, None


def _default_preflight(binary: str, state: dict) -> str | None:
    proxy = state.get("proxy") or {}
    if not proxy.get("needs_sdk"):
        return None
    keys = (
        "OBENCH_OPENCODE_BIN",
        "OBENCH_OPENCODE_CONFIG_JSON",
        "OBENCH_OPENCODE_PERMISSION_CONFIG",
        "OBENCH_OPENCODE_PROXY",
    )
    saved = {key: os.environ.get(key) for key in keys}
    row = None
    try:
        os.environ["OBENCH_OPENCODE_BIN"] = binary
        if state.get("config"):
            os.environ["OBENCH_OPENCODE_CONFIG_JSON"] = json.dumps(state["config"])
        else:
            os.environ.pop("OBENCH_OPENCODE_CONFIG_JSON", None)
        os.environ["OBENCH_OPENCODE_PERMISSION_CONFIG"] = (
            "1" if state.get("permission_config") else "0"
        )
        os.environ["OBENCH_OPENCODE_PROXY"] = json.dumps(proxy)
        from obench.adapters import opencode as opencode_adapter
        with tempfile.TemporaryDirectory(prefix="opencode-preflight-") as tmp:
            row = opencode_adapter.run("Reply with ok.", tmp, "claude-opus-5-5", 60)
    except FileNotFoundError as exc:
        return f"preflight failed: {exc}"
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return preflight_stop_reason(row)


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
          worker=None, proxy_url=None, model_route="proxy", preflight_fn=None,
          transcripts_dir=None, aa: bool = False, fixtures=None,
          order: str = "sides", seed: int | None = None, with_aa: bool = False,
          no_progress_s: float = 300):
    """Build, assess, and run. Returns ``(plan_text, launched, stopped_reason)``.

    ``tasks`` is one tuple shared by every PR, or a ``{pr: tasks}`` map.
    ``aa`` runs the parent SHA on ``aa-1`` and ``aa-2``. Both sides share
    the prepared binary for that SHA. ``with_aa`` runs without, with, aa-1,
    and aa-2 into the same output directory. ``order`` is ``sides``,
    ``interleave``, or ``random`` (with ``seed``).
    """
    out_dir = Path(out_dir)
    cache = Path(cache).resolve()
    if not isinstance(tasks, dict):
        tasks = tuple(tasks)
    plan = format_plan(
        prs, tasks, trials, aa=aa, fixtures=fixtures, with_aa=with_aa,
        order=order, seed=seed,
    )
    if dry_run:
        return plan, 0, None
    if aa or with_aa:
        for pr in prs:
            publish_text(out_dir / pr.pr / "arm.json", json.dumps({
                "arm": "parent-vs-parent",
                "sha": pr.without_sha,
                "sides": list(AA_SIDES),
            }, sort_keys=True))
    own_assess = assess_fn is None
    build_fn = build_fn or _default_build
    worker = worker or execute_cell
    if own_assess and preflight_fn is None:
        preflight_fn = _default_preflight
    tasks_dir_s = str(tasks_dir)
    adapters = _adapters_dir()
    prepared: dict[tuple[str, str], dict] = {}
    pending = []
    scheduled = order_cells(
        plan_cells(prs, tasks, trials, aa=aa, fixtures=fixtures, with_aa=with_aa),
        order=order,
        seed=seed,
    )
    for spec in scheduled:
        path = cell_file(out_dir, spec["pr"], spec["side"], spec["task"], spec["trial"])
        if read_cell(path) is not None:
            _absorb_finished(spec, out_dir, prepared)
            continue
        pending.append(spec)
    announced: set[tuple[str, str, str]] = set()
    server = None
    ledger_dir = (out_dir / "proxy-ledger").resolve()
    if own_assess and proxy_url is None and _needs_proxy(prs, model_route):
        from thesis.ab.vertex_anthropic_proxy import ProxyError, start_from_env
        try:
            server = start_from_env(ledger_dir=ledger_dir)
        except ProxyError as exc:
            raise RunError(str(exc)) from exc
        proxy_url = server.base_url

    def materialize(spec: dict) -> dict | None:
        sha = spec["sha"]
        repo = spec.get("repo") or ""
        key = (repo, sha)
        if key in prepared and not prepared[key].get("ok", True):
            _record_stopped(out_dir, spec, prepared[key])
            return None
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
                elif assessment.status == "infra":
                    prepared[key] = {
                        "ok": False,
                        "reason": assessment.reason,
                        "status": "infra",
                    }
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
                    decorated, pin_error = _decorate_toolchain(prepared[key], cache, sha, repo)
                    tool = decorated.get("toolchain")
                    if pin_error:
                        prepared[key] = {"ok": False, "reason": pin_error, "toolchain": tool}
                    else:
                        prepared[key] = decorated
                        if preflight_fn is not None:
                            reason = preflight_fn(str(decorated["binary"]), decorated)
                            if reason:
                                prepared[key] = {
                                    "ok": False,
                                    "reason": reason,
                                    "toolchain": tool,
                                }
        state = prepared[key]
        write_toolchain(out_dir, spec["pr"], spec["side"], state.get("toolchain"))
        if not state["ok"]:
            _record_stopped(out_dir, spec, state)
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
        filled = _fill(
            spec, state, out_dir, tasks_dir_s, adapters, model, timeout_s,
            transcripts_root=transcripts_dir,
            no_progress_s=no_progress_s,
        )
        if server is not None:
            filled = bind_cell_proxy(filled, ledger_dir)
            fault = ""
            cell_fixtures = filled.get("fixtures")
            if isinstance(cell_fixtures, dict):
                fault = str(cell_fixtures.get("fault") or "").strip()
            if fault:
                cell_id = str((filled.get("proxy") or {}).get("cell_id") or "")
                count = 1
                raw_count = cell_fixtures.get("fault_count") if isinstance(cell_fixtures, dict) else None
                if isinstance(raw_count, int) and not isinstance(raw_count, bool) and raw_count > 0:
                    count = raw_count
                server.arm_fault(cell_id, fault, count)
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
                _absorb_finished(spec, out_dir, prepared)
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
                    _absorb_finished(spec, out_dir, prepared)
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
    parser.add_argument(
        "--tasks", "--task",
        action="append",
        default=[],
        help="task name, or comma-separated names. With --task-map, keeps only those names from each PR's row.",
    )
    parser.add_argument(
        "--task-map",
        type=Path,
        default=None,
        help=(
            "CSV (pr,task,status[,options]) of per-PR trigger tasks. "
            "Replaces the default task set. options is applied to that PR's cells. "
            "Pass --task as well to keep only those mapped names "
            "(PR 4204 maps to two tasks; --task trig-subagent-followup screens one)."
        ),
    )
    parser.add_argument(
        "--aa",
        action="store_true",
        help=(
            "Parent-vs-parent noise arm. Run the parent build on aa-1 and aa-2. "
            "Not a without/with harness comparison. Both sides reuse that parent binary."
        ),
    )
    parser.add_argument(
        "--with-aa",
        action="store_true",
        help=(
            "Run without, with, aa-1, and aa-2 in one schedule. Cells land in the "
            "same --out directory (without.jsonl, with.jsonl, aa-1.jsonl, aa-2.jsonl, "
            "arm.json). The default order shuffles those four inside each trial block; "
            "pass --seed, or --order interleave for a fixed order."
        ),
    )
    parser.add_argument(
        "--order",
        choices=("sides", "interleave", "random"),
        default="sides",
        help=(
            "Launch order. sides runs every A cell, then every B cell. "
            "interleave alternates sides inside each trial. "
            "random shuffles each trial block; requires --seed."
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help=(
            "Seed for per-cell randomness, such as the webfetch colour, recorded "
            "on each cell. Also shuffles --order random, which requires it. "
            "--order interleave keeps its fixed order when a seed is set."
        ),
    )
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
    parser.add_argument(
        "--no-progress-s",
        type=float,
        default=300,
        help=(
            "Kill the agent when stdout, OpenCode logs and storage, and "
            "metered proxy bytes are all idle for this many seconds. "
            "0 disables the watchdog. A fatal Aborted( or tree-sitter wasm "
            "ENOENT still kills immediately while the watchdog is on."
        ),
    )
    parser.add_argument("--out", type=Path, default=Path("results/ab"))
    parser.add_argument(
        "--transcripts-dir",
        type=Path,
        default=None,
        help=(
            "Root for local transcripts, OpenCode session storage, and logs. "
            "Defaults to <out>/<pr>/transcripts."
        ),
    )
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
    if args.no_progress_s < 0:
        print("error: --no-progress-s must be >= 0", file=sys.stderr)
        return 2
    if args.aa and args.with_aa:
        print("error: pass either --aa or --with-aa", file=sys.stderr)
        return 2
    order = args.order
    if args.with_aa and order == "sides":
        order = "random"
    if order == "random" and args.seed is None:
        if args.with_aa and args.order == "sides":
            print(
                "error: --with-aa shuffles each trial block; pass --seed N, "
                "or --order interleave for a fixed order",
                file=sys.stderr,
            )
        else:
            print("error: --order random requires --seed", file=sys.stderr)
        return 2
    if args.seed is not None and order not in {"random", "interleave"}:
        print(
            "error: --seed applies to --order random and --order interleave",
            file=sys.stderr,
        )
        return 2
    try:
        prs = select_prs(parse_prs(args.prs), args.pr or None)
        fixtures = None
        if args.task_map is not None:
            mapping = load_task_map(args.task_map)
            prs, tasks = select_task_map(prs, mapping, args.task_map, explicit=bool(args.pr))
            if args.tasks:
                wanted = resolve_tasks(args.tasks)
                prs, tasks = restrict_mapped_tasks(
                    prs, tasks, wanted, explicit=bool(args.pr),
                )
            resolve_tasks([name for chosen in tasks.values() for name in chosen])
            fixtures = {pr.pr: mapping[pr.pr].options for pr in prs}
        else:
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
            transcripts_dir=args.transcripts_dir, aa=args.aa,
            fixtures=fixtures, order=order, seed=args.seed, with_aa=args.with_aa,
            no_progress_s=args.no_progress_s,
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
