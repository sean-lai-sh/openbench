"""Seeded draw of failed trials for credit assignment (SEA-111).

The draw is the set later stages score. It does not run the locator, a judge,
or a model. Rule 2 (``cap_cutoff``) is a filter here. ``credit_locator`` is
unchanged.

For each cell ``failed_trials()`` admits (``set_aside_count <= max_set_aside``):

1. Start from that output (completed failures of an admitted cell).
2. Remove ``cap_cutoff`` trials.
3. Remove trials with no trace.
4. Draw.

.. code-block:: python

    cell = "<model>/<task>"          # "@<patch_id>" when patch_id is set
    digest = sha256(("sea111-" + cell).encode("utf-8")).hexdigest()
    picks = random.Random(int(digest, 16)).sample(sorted(eligible_trial_ids), n_pick)

``n_pick`` defaults to 3. ``n_pick == "all"`` draws every eligible failure.
Picks stay in draw order. A cell over the set-aside cap is ``EXCLUDED`` and
nothing is drawn; its ``cap_cutoff`` trials are still listed. The reason is
the count (``max_set_aside=3: 5 set-aside (provider_blocked) trials > 3``),
never a task name.

    python3 -m obench.reflection.credit_draw --run <run dir> [--n-pick 3|all] [--max-set-aside 3] [--config draw.json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from obench.reflection.credit_locator import (
    MAX_SET_ASIDE, SET_ASIDE_STATUSES, cell_key, check_max_set_aside, failed_trials, read_trace,
    set_aside_counts, step_error,
)

SCHEMA = "openbench.reflection.credit_draw/v1"
TABLE = "credit_draw.json"
CELL_DIR = "credit_draw"
N_PICK = 3
SEED_PREFIX = "sea111-"


@dataclass(frozen=True)
class DrawConfig:
    n_pick: int | str = N_PICK
    max_set_aside: int = MAX_SET_ASIDE

    @classmethod
    def from_dict(cls, raw: dict) -> "DrawConfig":
        unknown = set(raw) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError(f"unknown draw config keys: {sorted(unknown)}")
        cfg = cls(**raw)
        check_n_pick(cfg.n_pick)
        check_max_set_aside(cfg.max_set_aside)
        return cfg


def check_n_pick(value: int | str) -> int | str:
    if value == "all":
        return "all"
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"n_pick must be a positive int or 'all', got {value!r}")
    return value


def draw_cell(model: str, task: str, patch_id: str | None) -> str:
    """Seed key. Baseline cells are ``<model>/<task>``; a patch adds ``@<patch_id>``."""
    name = f"{model}/{task}"
    if patch_id is not None:
        return f"{name}@{patch_id}"
    return name


def seed_string(cell: str) -> str:
    return SEED_PREFIX + cell


def seed_sha256(cell: str) -> str:
    return hashlib.sha256(seed_string(cell).encode("utf-8")).hexdigest()


def is_cap_cutoff(trial: dict, steps: list[dict]) -> bool:
    """Rule 2: a timeout that hit the cap, with a trace and no tool error anywhere in it.

    ``steps`` empty means there is no trace to search, so the trial is not
    ``cap_cutoff`` (it is no-trace). A timeout whose trace has a tool error
    (``step_error``) stays eligible.
    """
    if not trial.get("timed_out") or not steps:
        return False
    return not any(step_error(step) for step in steps)


def seeded_sample(cell: str, trial_ids: list[str], n_pick: int | str) -> list[str]:
    """Draw order. The whole pool when ``n_pick`` is ``all`` or larger than the pool."""
    ordered = sorted(trial_ids)
    if not ordered:
        return []
    n_pick = check_n_pick(n_pick)
    k = len(ordered) if n_pick == "all" else min(n_pick, len(ordered))
    digest = seed_sha256(cell)
    return random.Random(int(digest, 16)).sample(ordered, k)


def _steps_of(run_dir: Path) -> Callable[[dict], list[dict]]:
    def load(trial: dict) -> list[dict]:
        rel = trial.get("trace")
        if not rel or not isinstance(rel, str):
            return []
        return read_trace(run_dir / rel)
    return load


def partition_failures(
    trials: list[dict], steps_of: Callable[[dict], list[dict]],
) -> tuple[list[dict], list[dict], list[dict]]:
    """``(eligible, cap_cutoff, no_trace)`` from one cell's completed failures.

    Order is the rule: drop ``cap_cutoff``, then drop trials with no trace.
    The draw passes ``failed_trials()`` output. An excluded cell passes its
    completed failures only so the manifest can list what rule 2 would drop;
    that result is not drawn.
    """
    after_cap: list[tuple[dict, list[dict]]] = []
    cap: list[dict] = []
    for trial in trials:
        steps = steps_of(trial)
        if is_cap_cutoff(trial, steps):
            cap.append(trial)
        else:
            after_cap.append((trial, steps))
    eligible: list[dict] = []
    no_trace: list[dict] = []
    for trial, steps in after_cap:
        if steps:
            eligible.append(trial)
        else:
            no_trace.append(trial)
    return eligible, cap, no_trace


def _listed(trials: list[dict]) -> list[dict]:
    rows = [{"slot": trial.get("trial_index"), "trial_id": trial["trial_id"]} for trial in trials]

    def sort_key(row: dict) -> tuple:
        slot = row["slot"]
        return (slot is None, slot if isinstance(slot, int) else 0, row["trial_id"])

    rows.sort(key=sort_key)
    return rows


def _completed_failures(rows: list[dict]) -> list[dict]:
    return [row for row in rows if row.get("status") == "completed" and row.get("passed") is False]


def _exclusion_reason(count: int, rows: list[dict], max_set_aside: int) -> str:
    kinds = sorted({row.get("status") for row in rows if row.get("status") in SET_ASIDE_STATUSES})
    label = ", ".join(kinds) if kinds else "set-aside"
    return f"max_set_aside={max_set_aside}: {count} set-aside ({label}) trials > {max_set_aside}"


def _manifest_name(cell: str) -> str:
    safe = cell.replace("/", "__").replace("\\", "__")
    if not safe or safe in (".", "..") or "/" in safe or "\\" in safe:
        raise ValueError(f"cell name {cell!r} is not a safe manifest filename")
    return safe + ".json"


def _write_json(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _record(cell: str, model, task, patch_id, count: int, max_set_aside: int, n_pick: int | str) -> dict:
    return {
        "schema": SCHEMA, "cell": cell, "model": model, "task": task, "patch_id": patch_id,
        "status": "IN", "reason": None,
        "seed_string": seed_string(cell), "seed_sha256": seed_sha256(cell),
        "eligible_pool": 0, "n_pick": n_pick, "picks": [],
        "cap_cutoff_dropped": [], "no_trace_count": 0, "no_trace_trials": [],
        "set_aside_count": count, "max_set_aside": max_set_aside,
    }


def _read_rows(run_dir: Path) -> list[dict]:
    path = run_dir / "trials.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def run_draw(run_dir: Path, n_pick: int | str = N_PICK, max_set_aside: int = MAX_SET_ASIDE) -> dict[str, dict]:
    """Write ``credit_draw.json`` and one manifest per cell. A rerun replaces them."""
    run_dir = Path(run_dir)
    n_pick = check_n_pick(n_pick)
    max_set_aside = check_max_set_aside(max_set_aside)
    rows = _read_rows(run_dir)
    counts = set_aside_counts(rows)
    # Admission is #277's rule, via failed_trials(). Cells over the cap are absent here.
    admitted: dict[tuple, list[dict]] = {}
    for trial in failed_trials(run_dir, max_set_aside=max_set_aside):
        admitted.setdefault(cell_key(trial), []).append(trial)

    grouped: dict[tuple, list[dict]] = {}
    for row in rows:
        grouped.setdefault(cell_key(row), []).append(row)

    steps_of = _steps_of(run_dir)
    manifests: dict[str, dict] = {}
    for key in sorted(grouped, key=lambda item: draw_cell(item[1], item[0], item[2])):
        task, model, patch_id = key
        name = draw_cell(model, task, patch_id)
        count = counts.get(key, 0)
        group = grouped[key]
        rec = _record(name, model, task, patch_id, count, max_set_aside, n_pick)
        if count > max_set_aside:
            # Not admitted. List cap_cutoff and no-trace failures; do not draw.
            _ignored, cap, no_trace = partition_failures(_completed_failures(group), steps_of)
            rec.update(status="EXCLUDED", reason=_exclusion_reason(count, group, max_set_aside),
                       eligible_pool=0, picks=[],
                       cap_cutoff_dropped=_listed(cap), no_trace_count=len(no_trace), no_trace_trials=_listed(no_trace))
            manifests[name] = rec
            continue
        # Pool order: failed_trials() output, drop cap_cutoff, drop no-trace, then draw.
        eligible, cap, no_trace = partition_failures(admitted.get(key, []), steps_of)
        by_id: dict[str, dict] = {}
        for trial in eligible:
            by_id.setdefault(trial["trial_id"], trial)
        chosen = seeded_sample(name, list(by_id), n_pick)
        rec.update(status="IN", reason=None, eligible_pool=len(by_id),
                   picks=[{"draw_order": i + 1, "slot": by_id[tid].get("trial_index"), "trial_id": tid}
                          for i, tid in enumerate(chosen)],
                   cap_cutoff_dropped=_listed(cap), no_trace_count=len(no_trace), no_trace_trials=_listed(no_trace))
        manifests[name] = rec

    _write_json(run_dir / TABLE, manifests)
    cell_dir = run_dir / CELL_DIR
    cell_dir.mkdir(parents=True, exist_ok=True)
    written = set()
    for name, rec in manifests.items():
        filename = _manifest_name(name)
        written.add(filename)
        _write_json(cell_dir / filename, rec)
    for leftover in cell_dir.glob("*.json"):
        if leftover.name not in written:
            leftover.unlink()
    return manifests


def resolve_config(config_path: Path | None = None, n_pick: int | str | None = None,
                   max_set_aside: int | None = None) -> DrawConfig:
    """Settings from ``--config``. ``--n-pick`` and ``--max-set-aside`` override the file."""
    cfg = DrawConfig.from_dict(json.loads(Path(config_path).read_text(encoding="utf-8"))) if config_path else DrawConfig()
    if n_pick is None and max_set_aside is None:
        return cfg
    raw = asdict(cfg)
    if n_pick is not None:
        raw["n_pick"] = n_pick
    if max_set_aside is not None:
        raw["max_set_aside"] = max_set_aside
    return DrawConfig.from_dict(raw)


def parse_n_pick(text: str) -> int | str:
    if text == "all":
        return "all"
    try:
        value = int(text, 10)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("n-pick must be a positive integer or 'all'") from None
    if value < 1:
        raise argparse.ArgumentTypeError("n-pick must be a positive integer or 'all'")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seeded draw of failed trials for credit assignment")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--config", type=Path, help="DrawConfig JSON (n_pick, max_set_aside)")
    parser.add_argument("--n-pick", type=parse_n_pick, default=None,
                        help="failures to draw per admitted cell (default 3, or 'all'; overrides --config)")
    parser.add_argument("--max-set-aside", type=int, default=None,
                        help="admit a cell when its set-aside trials are at most this many (default 3; overrides --config)")
    args = parser.parse_args(argv)
    cfg = resolve_config(args.config, n_pick=args.n_pick, max_set_aside=args.max_set_aside)
    manifests = run_draw(args.run, n_pick=cfg.n_pick, max_set_aside=cfg.max_set_aside)
    print(json.dumps({
        "table": str(args.run / TABLE),
        "cells": len(manifests),
        "in": sum(1 for rec in manifests.values() if rec["status"] == "IN"),
        "excluded": sum(1 for rec in manifests.values() if rec["status"] == "EXCLUDED"),
        "picks": sum(len(rec["picks"]) for rec in manifests.values()),
        "n_pick": cfg.n_pick, "max_set_aside": cfg.max_set_aside,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
