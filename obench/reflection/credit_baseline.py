"""Fresh N-trial baseline for each admitted credit-assignment cell (SEA-111).

The draw (``credit_draw.py``) decides which cells are admitted. This step runs
a new baseline for each of those cells at the current checkout, then
``ideation.evaluate`` compares selection against that row.

The image is the one recorded on the cell's original trials (``image_ref``,
``image_id``, ``image_matches_pin``). It is passed through as
``recorded_image`` and is not re-pinned. The smoke-compaction knob is off,
including when ``OBENCH_SMOKE_COMPACTION`` is set. ``EXCLUDED`` and ``NO_ROWS``
cells are not run.

The manifest is ``credit_baseline.json`` in the run directory, plus one file
per cell under ``credit_baseline/``. Trial output lives under
``credit_baseline/runs/`` and does not modify ``trials.jsonl``.

``evaluate`` reads this manifest. A cell with no fresh baseline is an error.
The pilot ``summary.jsonl`` row is not a fallback.

    python3 -m obench.reflection.credit_baseline --run <run dir> --cells <cell list> --fixture <passes.json> [--n-trials 30]
    python3 -m obench.reflection.credit_baseline --run <run dir> --cells <cell list> --live --opencode <bin/<sha>/opencode> [--n-trials 30] [--max-usd D] [--max-usd-per-cell D] [--workers N]

``--max-usd`` is the invocation total. ``--max-usd-per-cell`` is the runner's
``spend_cap_usd`` check for one ``(model, task)`` cell. Both are optional and
must be > 0 when set. A cap stop keeps the rows already written, records
``stop_reason``, and exits 0. ``--workers`` (default 1) is the runner's
concurrency for one cell. Cells run one at a time.

``--fixture`` is the offline pass table. ``--live`` builds the ``CellExecutor``
``python3 -m obench.reflection.runner --cell`` builds and passes it to
``run_baselines``. Exactly one of the two is required.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

from obench.reflection import credit_draw as draw
from obench.reflection import runner as rn
from obench.reflection.credit_locator import MAX_SET_ASIDE, cell_key, check_max_set_aside, set_aside_counts

SCHEMA = "openbench.reflection.credit_baseline/v1"
TABLE = "credit_baseline.json"
CELL_DIR = "credit_baseline"
RUNS_DIR = "runs"


class BaselineError(Exception):
    pass


def recorded_image(cell: str, rows: list[dict]) -> dict:
    """The single image the cell's original trials ran.

    Rows with no image fields are ignored. Two different images, or no image
    at all, is an error: this step does not pick one and does not re-pin.
    """
    seen: list[tuple] = []
    for row in rows:
        ref, image_id, matches = row.get("image_ref"), row.get("image_id"), row.get("image_matches_pin")
        if ref is None and image_id is None and matches is None:
            continue
        seen.append((ref, image_id, matches))
    if not seen:
        raise BaselineError(f"{cell}: no recorded image on its trials; refusing to re-pin")
    unique = set(seen)
    if len(unique) != 1:
        raise BaselineError(f"{cell}: {len(unique)} recorded images; refusing to re-pin or choose one")
    ref, image_id, matches = seen[0]
    if not isinstance(ref, str) or not ref:
        raise BaselineError(f"{cell}: recorded image has no ref; refusing to re-pin")
    if matches not in (True, False, None):
        raise BaselineError(f"{cell}: recorded image_matches_pin must be true, false, or null, got {matches!r}")
    return {"ref": ref, "id": image_id, "matches_pin": matches}


def _admitted(run_dir: Path, cells: list[str], max_set_aside: int) -> list[dict]:
    """Listed cells the draw would mark ``IN``. Does not write the draw.

    ``NO_ROWS`` and ``EXCLUDED`` cells are left out. Unlisted rows are not added.
    """
    rows = draw._read_rows(run_dir)
    counts = set_aside_counts(rows)
    grouped: dict[tuple, list[dict]] = {}
    for row in rows:
        grouped.setdefault(cell_key(row), []).append(row)
    admitted = []
    for name in draw.check_cells(list(cells)):
        model, task = name.split("/", 1)
        patch_id = None
        if "@" in task:
            task, patch_id = task.split("@", 1)
        key = (task, model, patch_id)
        group = grouped.get(key)
        if not group or counts.get(key, 0) > max_set_aside:
            continue
        admitted.append({"cell": name, "model": model, "task": task, "patch_id": patch_id, "rows": group})
    return admitted


def _write_json(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _plan_workers(plan: dict, workers: int) -> int:
    recorded = plan.get("workers")
    if isinstance(recorded, int) and not isinstance(recorded, bool):
        return recorded
    config = plan.get("config") if isinstance(plan.get("config"), dict) else {}
    recorded = config.get("workers")
    if isinstance(recorded, int) and not isinstance(recorded, bool):
        return recorded
    return workers


def _check_plan_knob(cell: str, plan: dict) -> str:
    """Commit and smoke-compaction checks shared by a finished and a capped baseline."""
    commit = (plan.get("code") or {}).get("commit")
    if not commit:
        raise BaselineError(f"{cell}: baseline run recorded no commit")
    if plan.get("config", {}).get("smoke_compaction"):
        raise BaselineError(f"{cell}: smoke compaction was on; the baseline knob must be off")
    profile = plan.get("smoke_compaction") or {}
    if profile.get("enabled"):
        raise BaselineError(f"{cell}: smoke compaction profile is enabled; the baseline knob must be off")
    return commit


def _baseline_row(cell: str, model: str, task: str, image: dict, summary: dict, plan: dict,
                  n_trials: int, rel: str, state: str, workers: int = 1) -> dict:
    commit = _check_plan_knob(cell, plan)
    profile = plan.get("smoke_compaction") or {}
    if summary.get("trials") != n_trials:
        raise BaselineError(f"{cell}: baseline ran {summary.get('trials')} trials, not {n_trials}")
    matches = image["matches_pin"]
    return {
        "schema": SCHEMA, "cell": cell, "model": model, "task": task, "patch_id": None,
        "n_trials": n_trials, "passes": summary["passes"], "completed": summary["completed"],
        "set_aside": summary["set_aside"], "provider_blocked": summary["provider_blocked"],
        "model_refused": summary["model_refused"], "cost_usd": summary["spend_usd"],
        "baseline_commit": commit, "code_commit": commit,
        "image": {"ref": image["ref"], "id": image["id"]},
        "image_source": "recorded", "image_matches_pin": matches,
        "image_matches_pin_false": matches is False, "smoke_compaction": False,
        "smoke_compaction_profile": profile, "run_dir": rel, "run_state": state,
        "workers": _plan_workers(plan, workers),
    }


def _check_fresh_image(cell: str, child: Path, image: dict) -> None:
    """A fresh trial that reports an image must report the recorded one."""
    refs, ids = set(), set()
    for row in rn.read_rows(child / "trials.jsonl"):
        if row.get("image_ref"):
            refs.add(row["image_ref"])
        if row.get("image_id"):
            ids.add(row["image_id"])
    if refs and refs != {image["ref"]}:
        raise BaselineError(
            f"{cell}: fresh trials ran {sorted(refs)}, not the recorded image {image['ref']}; refusing to re-pin")
    if image.get("id") and ids and ids != {image["id"]}:
        raise BaselineError(
            f"{cell}: fresh trials ran image id {sorted(ids)}, not the recorded id {image['id']}; refusing to re-pin")


def _publish_run(staging: Path, published: Path) -> None:
    """Move a checked run into the directory the manifest names.

    The previous run is kept until the new directory is in place. A failure
    before this call leaves that previous run, and the manifest that points
    at it, unchanged.
    """
    backup = published.with_name(published.name + ".replacing")
    if backup.exists():
        shutil.rmtree(backup)
    if published.exists():
        published.rename(backup)
    try:
        staging.rename(published)
    except Exception:
        if backup.exists() and not published.exists():
            backup.rename(published)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def _stopped_baseline_row(cell: str, model: str, task: str, image: dict, summary: dict, plan: dict,
                          n_trials: int, rel: str, status: dict, workers: int) -> dict:
    """A baseline the cap stopped before N trials. Not a scored baseline."""
    commit = _check_plan_knob(cell, plan)
    profile = plan.get("smoke_compaction") or {}
    matches = image["matches_pin"]
    reason = status.get("stop_reason") if status.get("stop_reason") in rn.CAP_STOP_REASONS else "max_usd_per_cell"
    return {
        "schema": SCHEMA, "cell": cell, "model": model, "task": task, "patch_id": None,
        "n_trials": n_trials, "passes": summary.get("passes"), "completed": summary.get("completed"),
        "set_aside": summary.get("set_aside"), "provider_blocked": summary.get("provider_blocked"),
        "model_refused": summary.get("model_refused"), "cost_usd": summary.get("spend_usd"),
        "baseline_commit": commit, "code_commit": commit,
        "image": {"ref": image["ref"], "id": image["id"]},
        "image_source": "recorded", "image_matches_pin": matches,
        "image_matches_pin_false": matches is False, "smoke_compaction": False,
        "smoke_compaction_profile": profile, "run_dir": rel, "run_state": status.get("state"),
        "workers": _plan_workers(plan, workers), "stopped_by_cap": True,
        "trials_completed": summary.get("trials", 0), "stop_reason": reason,
        "stop_cell": status.get("cell") or cell,
        "max_usd": status.get("max_usd"), "max_usd_per_cell": status.get("max_usd_per_cell"),
    }


def _run_one(run_dir: Path, base_cfg: dict, item: dict, image: dict, executor: rn.Executor,
             n_trials: int, workers: int = 1, ledger: rn.SpendLedger | None = None) -> tuple[dict, Path]:
    """Run into ``<slug>.incoming``. The caller publishes it.

    A cap stop is not an error: the rows already written stay, and the manifest
    row is ``stopped_by_cap``. Any other failure deletes the staging directory.
    """
    cell, model, task = item["cell"], item["model"], item["task"]
    if item["patch_id"] is not None:
        raise BaselineError(f"{cell}: fresh baseline runs the unpatched cell; a patched cell is not baselined here")
    slug = draw._manifest_name(cell).removesuffix(".json")
    staging = run_dir / CELL_DIR / RUNS_DIR / (slug + ".incoming")
    if staging.exists():
        shutil.rmtree(staging)
    rel = f"{CELL_DIR}/{RUNS_DIR}/{slug}"
    cell_cap = ledger.max_usd_per_cell if ledger is not None else None
    cfg = rn.RunConfig.from_dict({
        "run_id": f"{base_cfg['run_id']}--baseline--{slug}", "suite": base_cfg["suite"], "models": [model],
        "n_trials": n_trials, "tasks": [task], "max_rounds": 1, "fixed_tasks": True,
        "spend_cap_usd": cell_cap, "smoke_compaction": False, "recorded_image": image, "workers": workers,
    })
    try:
        with rn.arm_lock() as lock:
            status = rn.Runner(cfg, staging, executor, workers=workers, ledger=ledger).run()
            rn.stamp_arm_lock(staging, lock, ledger)
        _check_fresh_image(cell, staging, image)
        plan = json.loads((staging / "plan.json").read_text(encoding="utf-8"))
        matches = [row for row in rn.read_rows(staging / "summary.jsonl")
                   if row["task"] == task and row["model"] == model and row["patch_id"] is None]
        if rn.is_cap_status(status):
            summary = dict(matches[0]) if matches else {}
            if "trials" not in summary:
                summary["trials"] = len(rn.read_rows(staging / "trials.jsonl"))
            return _stopped_baseline_row(cell, model, task, image, summary, plan, n_trials, rel, status, workers), staging
        if status["state"] != "done":
            raise BaselineError(f"{cell}: baseline run state is {status['state']}, not done")
        if len(matches) != 1:
            raise BaselineError(f"{cell}: expected one baseline summary row, got {len(matches)}")
        return _baseline_row(cell, model, task, image, matches[0], plan, n_trials, rel, status["state"], workers), staging
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def run_baselines(run_dir: Path, cells: list[str], executor: rn.Executor, n_trials: int = rn.N_TRIALS,
                  max_set_aside: int = MAX_SET_ASIDE, max_usd: float | None = None,
                  max_usd_per_cell: float | None = None, workers: int = 1) -> dict[str, dict]:
    """Run one fresh baseline per admitted cell and write ``credit_baseline.json``.

    The executor's smoke-compaction knob is forced off for the call and restored
    afterwards. Admitted means the draw would mark the cell ``IN``. A rerun
    that fails leaves the previous baseline manifest and its trial directory
    in place.

    ``max_usd`` stops the invocation. ``max_usd_per_cell`` is ``spend_cap_usd``
    for that cell and does not stop the other cells. Cells run one at a time;
    within a cell, ``workers`` trials run at once. A cap stop keeps every row
    already written.
    """
    run_dir = Path(run_dir)
    if isinstance(n_trials, bool) or not isinstance(n_trials, int) or n_trials < 1:
        raise BaselineError(f"n_trials must be a positive int, got {n_trials!r}")
    max_usd = rn.check_optional_usd("max_usd", max_usd)
    max_usd_per_cell = rn.check_optional_usd("max_usd_per_cell", max_usd_per_cell)
    workers = rn.check_workers(workers)
    max_set_aside = check_max_set_aside(max_set_aside)
    plan_path = run_dir / "plan.json"
    if not plan_path.is_file():
        raise BaselineError(f"{run_dir} has no plan.json")
    base_cfg = json.loads(plan_path.read_text(encoding="utf-8"))["config"]
    if not base_cfg.get("run_id") or not base_cfg.get("suite"):
        raise BaselineError(f"{plan_path} has no run_id or suite")
    prepared = []
    for item in _admitted(run_dir, cells, max_set_aside):
        if item["patch_id"] is not None:
            raise BaselineError(
                f"{item['cell']}: fresh baseline runs the unpatched cell; a patched cell is not baselined here")
        prepared.append((item, recorded_image(item["cell"], item["rows"])))
    ledger = None
    if max_usd is not None or max_usd_per_cell is not None:
        ledger = rn.SpendLedger(max_usd=max_usd, max_usd_per_cell=max_usd_per_cell)
        ledger.seed_run(run_dir)
    previous = getattr(executor, "smoke_compaction", None)
    if previous:
        executor.smoke_compaction = False
    staged: list[tuple[str, dict, Path]] = []
    try:
        for item, image in prepared:
            if ledger is not None and ledger.invocation_stop == "max_usd":
                break
            row, staging = _run_one(run_dir, base_cfg, item, image, executor, n_trials, workers, ledger)
            staged.append((item["cell"], row, staging))
    except Exception:
        for _, _, staging in staged:
            shutil.rmtree(staging, ignore_errors=True)
        raise
    finally:
        if previous:
            executor.smoke_compaction = previous
    previous_manifest = {}
    table = run_dir / TABLE
    if table.is_file():
        try:
            loaded = json.loads(table.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            loaded = {}
        if isinstance(loaded, dict):
            previous_manifest = loaded
    published_rows = []
    for name, row, staging in staged:
        published = staging.with_name(staging.name.removesuffix(".incoming"))
        prior = previous_manifest.get(name)
        # A cap stop did not finish N trials, so it does not replace a baseline
        # that already did. The partial run is kept beside it.
        keep_prior = (row.get("stopped_by_cap") and isinstance(prior, dict) and not prior.get("stopped_by_cap")
                      and published.is_dir())
        if keep_prior:
            kept = published.with_name(published.name + ".stopped")
            if kept.exists():
                shutil.rmtree(kept)
            staging.rename(kept)
            published_rows.append((name, prior))
        else:
            _publish_run(staging, published)
            published_rows.append((name, row))
    manifests = {name: row for name, row in published_rows}
    _write_json(run_dir / TABLE, manifests)
    cell_dir = run_dir / CELL_DIR
    cell_dir.mkdir(parents=True, exist_ok=True)
    written = set()
    for name, rec in manifests.items():
        filename = draw._manifest_name(name)
        written.add(filename)
        _write_json(cell_dir / filename, rec)
    for leftover in cell_dir.glob("*.json"):
        if leftover.name not in written:
            leftover.unlink()
    return manifests


def fresh_baseline_row(run_dir: Path, task: str, model: str) -> dict:
    """The fresh baseline for an unpatched cell. Missing is an error.

    There is no fallback to the pilot ``summary.jsonl`` row.
    """
    cell = f"{model}/{task}"
    path = Path(run_dir) / TABLE
    if not path.is_file():
        raise ValueError(f"no fresh baseline for {task} / {model}; "
                         "refusing to score selection or confirmation against the old summary row")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"fresh baseline {path} is unreadable; refusing to score against the old summary row") from exc
    row = doc.get(cell) if isinstance(doc, dict) else None
    if not isinstance(row, dict) or "passes" not in row or "completed" not in row:
        raise ValueError(f"no fresh baseline for {task} / {model}; "
                         "refusing to score selection or confirmation against the old summary row")
    return row


def _live_executor(args):
    """The ``CellExecutor`` ``runner --cell`` builds for a paid trial.

    Same constructor call as ``obench.reflection.runner.main``: pinned
    OpenCode, ADC token, default estimates, and the image flags. Smoke
    compaction is off for this baseline even when ``OBENCH_SMOKE_COMPACTION``
    is set. ``run_baselines`` forces that knob off for the trials and
    restores it afterwards.
    """
    from obench.reflection.cell_executor import DEFAULT_ESTIMATES_USD, CellExecutor
    from thesis.ab.vertex_anthropic_proxy import AdcToken

    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
    if not project or not args.opencode:
        raise SystemExit("--live needs GOOGLE_CLOUD_PROJECT and --opencode")
    token = AdcToken()
    token()  # fail before any trial if credentials are missing
    return CellExecutor(args.opencode, project, token, estimates_usd={**DEFAULT_ESTIMATES_USD, **(args.estimates or {})},
                        default_image=args.default_image, use_image_tag=args.use_image_tag,
                        smoke_compaction=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fresh N-trial baseline for admitted credit-assignment cells")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--cells", type=Path, required=True, help="candidate cells, one <model>/<task> key per line or a JSON array")
    parser.add_argument("--n-trials", type=int, default=rn.N_TRIALS, help="trials per admitted cell (default 30)")
    parser.add_argument("--max-set-aside", type=int, default=None, help="admit a cell at or under this many set-aside trials (default 3)")
    parser.add_argument("--max-usd", type=rn.positive_usd_arg, default=None,
                        help="stop the invocation before the trial that would pass this total (optional, > 0)")
    parser.add_argument("--max-usd-per-cell", type=rn.positive_usd_arg, default=None,
                        help="per (model, task) cell cap; the spend_cap_usd check (optional, > 0). "
                             "Other cells continue. Intended use: 1.5x that cell's estimate")
    parser.add_argument("--workers", type=rn.positive_workers_arg, default=1,
                        help="trials of one cell at once (default 1). Cells themselves run one at a time")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fixture", type=Path,
                      help='offline pass table {"task|model": passes}. Does not call a provider.')
    mode.add_argument("--live", action="store_true",
                      help="paid trials: the CellExecutor runner --cell builds (needs GOOGLE_CLOUD_PROJECT and --opencode)")
    parser.add_argument("--opencode", type=Path, help="--live: the pinned OpenCode binary (bin/<sha>/opencode)")
    parser.add_argument("--estimates", type=json.loads, default=None,
                        help='--live: per-trial USD estimates, e.g. {"claude-opus-5-5": 2.0}')
    parser.add_argument("--default-image", default="h1-env:1027-strace",
                        help="--live: agent image for tasks that name none (openbench-tb-hard)")
    parser.add_argument("--use-image-tag", action="store_true",
                        help="--live: when a task.toml digest ref isn't on this host, run its docker_image_tag (recorded)")
    args = parser.parse_args(argv)
    if isinstance(args.n_trials, bool) or args.n_trials < 1:
        raise SystemExit("n-trials must be a positive integer")
    if args.fixture is not None:
        raw = json.loads(args.fixture.read_text(encoding="utf-8"))
        executor = rn.FixtureExecutor({tuple(k.split("|", 1)): int(v) for k, v in raw.items()})
    else:
        executor = _live_executor(args)
    try:
        manifests = run_baselines(
            args.run, draw.load_cells(args.cells), executor, n_trials=args.n_trials,
            max_set_aside=MAX_SET_ASIDE if args.max_set_aside is None else args.max_set_aside,
            max_usd=args.max_usd, max_usd_per_cell=args.max_usd_per_cell, workers=args.workers)
    except (BaselineError, rn.RunnerError, ValueError) as exc:
        raise SystemExit(str(exc)) from None
    stopped = {name: {"stop_reason": rec.get("stop_reason"), "cell": rec.get("stop_cell") or name,
                      "trials_completed": rec.get("trials_completed")}
               for name, rec in sorted(manifests.items()) if rec.get("stopped_by_cap")}
    print(json.dumps({
        "table": str(args.run / TABLE), "cells": len(manifests), "n_trials": args.n_trials,
        "workers": args.workers, "max_usd": args.max_usd, "max_usd_per_cell": args.max_usd_per_cell,
        "stop_reason": "max_usd" if any(item["stop_reason"] == "max_usd" for item in stopped.values()) else None,
        "stopped_cells": stopped,
        "passes": {name: rec["passes"] for name, rec in sorted(manifests.items())},
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
