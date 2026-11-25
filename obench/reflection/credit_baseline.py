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


def _baseline_row(cell: str, model: str, task: str, image: dict, summary: dict, plan: dict,
                  n_trials: int, rel: str, state: str) -> dict:
    commit = (plan.get("code") or {}).get("commit")
    if not commit:
        raise BaselineError(f"{cell}: baseline run recorded no commit")
    if plan.get("config", {}).get("smoke_compaction"):
        raise BaselineError(f"{cell}: smoke compaction was on; the baseline knob must be off")
    profile = plan.get("smoke_compaction") or {}
    if profile.get("enabled"):
        raise BaselineError(f"{cell}: smoke compaction profile is enabled; the baseline knob must be off")
    if summary.get("trials") != n_trials:
        raise BaselineError(f"{cell}: baseline ran {summary.get('trials')} trials, not {n_trials}")
    matches = image["matches_pin"]
    return {
        "schema": SCHEMA, "cell": cell, "model": model, "task": task, "patch_id": None,
        "n_trials": n_trials, "passes": summary["passes"], "completed": summary["completed"],
        "set_aside": summary["set_aside"], "provider_blocked": summary["provider_blocked"],
        "model_refused": summary["model_refused"], "cost_usd": summary["spend_usd"],
        "baseline_commit": commit, "image": {"ref": image["ref"], "id": image["id"]},
        "image_source": "recorded", "image_matches_pin": matches,
        "image_matches_pin_false": matches is False, "smoke_compaction": False,
        "smoke_compaction_profile": profile, "run_dir": rel, "run_state": state,
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


def _run_one(run_dir: Path, base_cfg: dict, item: dict, image: dict, executor: rn.Executor,
             n_trials: int) -> tuple[dict, Path]:
    """Run into ``<slug>.incoming``. The caller publishes it after every cell succeeds."""
    cell, model, task = item["cell"], item["model"], item["task"]
    if item["patch_id"] is not None:
        raise BaselineError(f"{cell}: fresh baseline runs the unpatched cell; a patched cell is not baselined here")
    slug = draw._manifest_name(cell).removesuffix(".json")
    staging = run_dir / CELL_DIR / RUNS_DIR / (slug + ".incoming")
    if staging.exists():
        shutil.rmtree(staging)
    rel = f"{CELL_DIR}/{RUNS_DIR}/{slug}"
    cfg = rn.RunConfig.from_dict({
        "run_id": f"{base_cfg['run_id']}--baseline--{slug}", "suite": base_cfg["suite"], "models": [model],
        "n_trials": n_trials, "tasks": [task], "max_rounds": 1, "fixed_tasks": True,
        "smoke_compaction": False, "recorded_image": image,
    })
    try:
        status = rn.Runner(cfg, staging, executor).run()
        if status["state"] != "done":
            raise BaselineError(f"{cell}: baseline run state is {status['state']}, not done")
        _check_fresh_image(cell, staging, image)
        plan = json.loads((staging / "plan.json").read_text(encoding="utf-8"))
        summaries = [row for row in rn.read_rows(staging / "summary.jsonl")
                     if row["task"] == task and row["model"] == model and row["patch_id"] is None]
        if len(summaries) != 1:
            raise BaselineError(f"{cell}: expected one baseline summary row, got {len(summaries)}")
        return _baseline_row(cell, model, task, image, summaries[0], plan, n_trials, rel, status["state"]), staging
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def run_baselines(run_dir: Path, cells: list[str], executor: rn.Executor, n_trials: int = rn.N_TRIALS,
                  max_set_aside: int = MAX_SET_ASIDE) -> dict[str, dict]:
    """Run one fresh baseline per admitted cell and write ``credit_baseline.json``.

    The executor's smoke-compaction knob is forced off for the call and restored
    afterwards. Admitted means the draw would mark the cell ``IN``. A rerun
    that fails leaves the previous baseline manifest and its trial directory
    in place.
    """
    run_dir = Path(run_dir)
    if isinstance(n_trials, bool) or not isinstance(n_trials, int) or n_trials < 1:
        raise BaselineError(f"n_trials must be a positive int, got {n_trials!r}")
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
    previous = getattr(executor, "smoke_compaction", None)
    if previous:
        executor.smoke_compaction = False
    staged: list[tuple[str, dict, Path]] = []
    try:
        for item, image in prepared:
            row, staging = _run_one(run_dir, base_cfg, item, image, executor, n_trials)
            staged.append((item["cell"], row, staging))
    except Exception:
        for _, _, staging in staged:
            shutil.rmtree(staging, ignore_errors=True)
        raise
    finally:
        if previous:
            executor.smoke_compaction = previous
    for _, row, staging in staged:
        _publish_run(staging, staging.with_name(staging.name.removesuffix(".incoming")))
    manifests = {name: row for name, row, _ in staged}
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fresh N-trial baseline for admitted credit-assignment cells")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--cells", type=Path, required=True, help="candidate cells, one <model>/<task> key per line or a JSON array")
    parser.add_argument("--n-trials", type=int, default=rn.N_TRIALS, help="trials per admitted cell (default 30)")
    parser.add_argument("--max-set-aside", type=int, default=None, help="admit a cell at or under this many set-aside trials (default 3)")
    parser.add_argument("--fixture", type=Path, required=True,
                        help='offline pass table {"task|model": passes}. This command does not call a provider.')
    args = parser.parse_args(argv)
    if isinstance(args.n_trials, bool) or args.n_trials < 1:
        raise SystemExit("n-trials must be a positive integer")
    raw = json.loads(args.fixture.read_text(encoding="utf-8"))
    executor = rn.FixtureExecutor({tuple(k.split("|", 1)): int(v) for k, v in raw.items()})
    try:
        manifests = run_baselines(
            args.run, draw.load_cells(args.cells), executor, n_trials=args.n_trials,
            max_set_aside=MAX_SET_ASIDE if args.max_set_aside is None else args.max_set_aside)
    except (BaselineError, rn.RunnerError, ValueError) as exc:
        raise SystemExit(str(exc)) from None
    print(json.dumps({
        "table": str(args.run / TABLE), "cells": len(manifests), "n_trials": args.n_trials,
        "passes": {name: rec["passes"] for name, rec in sorted(manifests.items())},
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
