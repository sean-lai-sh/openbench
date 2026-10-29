"""Per-cell env, rerun, rescore, and quarantine columns.

Reruns and rescores write a new results folder. They never replace the
original cell file. Scoring drops:

* ``env_failure`` (checker killed by its own timeout, ``env_cause=checker_timeout``)
* ``suspect_startup_exit`` (wall under 30s and output tokens under 500), which
  is not a wrong answer; it waits on a log check
* a results-folder ``quarantine.txt`` label (for example ``pre_fix_runner``)
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

SUSPECT_STARTUP_WALL_S = 30
SUSPECT_STARTUP_OUTPUT_TOKENS = 500
QUARANTINE_FILENAME = "quarantine.txt"
ENV_CAUSE_CHECKER_TIMEOUT = "checker_timeout"

CELL_ENV_FIELDS = (
    "checker_timeout_s",
    "env_failure",
    "env_cause",
    "rerun_of",
    "rescored_from",
    "suspect_startup_exit",
    "quarantine",
)


class CellWriteError(ValueError):
    """Raised when a rerun or rescore would overwrite an old cell."""


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def cell_id_of(row: dict) -> str:
    """Stable id already stored on a cell: gateway ``cell_id``, else ``run_id``."""
    if not isinstance(row, dict):
        return ""
    for key in ("cell_id", "run_id"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def output_tokens(row: dict):
    """Model output tokens. Vendor ``tokens_output`` wins, then the proxy split."""
    if not isinstance(row, dict):
        return None
    for key in ("tokens_output", "tokens_proxy_output"):
        value = _number(row.get(key))
        if value is not None:
            return value
    return None


def wall_seconds(row: dict):
    if not isinstance(row, dict):
        return None
    wall = _number(row.get("wall_time_s"))
    if wall is not None:
        return wall
    result = row.get("result")
    if isinstance(result, dict):
        return _number(result.get("duration_s"))
    return None


def checker_exit_of(row: dict):
    if not isinstance(row, dict):
        return None
    if row.get("checker_exit") is not None:
        return row.get("checker_exit")
    result = row.get("result")
    if isinstance(result, dict) and result.get("checker_exit") is not None:
        return result.get("checker_exit")
    return None


def compute_suspect_startup_exit(row: dict) -> bool:
    """True when the cell died before it could have answered.

    Wall time strictly under 30 seconds and output tokens strictly under 500.
    A missing wall or token count is not a startup exit.
    """
    wall = wall_seconds(row)
    if wall is None or wall >= SUSPECT_STARTUP_WALL_S:
        return False
    tokens = output_tokens(row)
    if tokens is None or tokens >= SUSPECT_STARTUP_OUTPUT_TOKENS:
        return False
    return True


def is_suspect_startup_exit(row: dict) -> bool:
    """Stored flag when the cell recorded one, otherwise the wall/token rule."""
    if not isinstance(row, dict):
        return False
    stored = row.get("suspect_startup_exit")
    if isinstance(stored, bool):
        return stored
    return compute_suspect_startup_exit(row)


def quarantine_label(row: dict) -> str:
    if not isinstance(row, dict):
        return ""
    value = row.get("quarantine")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return ""


def read_quarantine_file(directory: Path) -> str:
    path = Path(directory) / QUARANTINE_FILENAME
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    for line in text.splitlines():
        label = line.strip()
        if label and not label.startswith("#"):
            return label
    return ""


def folder_quarantine(start: Path, *, levels: int = 8) -> str:
    """Label from ``quarantine.txt`` on ``start`` or one of its parents."""
    current = Path(start)
    if not current.is_dir():
        current = current.parent
    for _ in range(levels):
        label = read_quarantine_file(current)
        if label:
            return label
        if current.parent == current:
            break
        current = current.parent
    return ""


def apply_folder_quarantine(rows, start: Path) -> str:
    """Stamp a folder label onto rows that do not already carry one."""
    label = folder_quarantine(Path(start))
    if not label:
        return ""
    for row in rows:
        if isinstance(row, dict) and not quarantine_label(row):
            row["quarantine"] = label
    return label


def stamp_env_columns(
    row: dict,
    *,
    checker_timeout_s=None,
    rerun_of=None,
    rescored_from=None,
    quarantine=None,
) -> dict:
    """Fill the env columns on ``row`` from the checker outcome and the caller."""
    if not isinstance(row, dict):
        return row
    if checker_timeout_s is not None:
        row["checker_timeout_s"] = checker_timeout_s
    elif "checker_timeout_s" not in row:
        row["checker_timeout_s"] = None
    if checker_exit_of(row) == "timeout":
        row["env_failure"] = True
        row["env_cause"] = ENV_CAUSE_CHECKER_TIMEOUT
    else:
        cause = row.get("env_cause")
        if cause in (None, "", ENV_CAUSE_CHECKER_TIMEOUT):
            row["env_failure"] = False
            row["env_cause"] = None
        else:
            row["env_failure"] = bool(row.get("env_failure"))
    if rerun_of is not None:
        row["rerun_of"] = rerun_of or None
    elif "rerun_of" not in row:
        env = os.environ.get("OBENCH_RERUN_OF", "").strip()
        row["rerun_of"] = env or None
    if rescored_from is not None:
        row["rescored_from"] = rescored_from or None
    elif "rescored_from" not in row:
        row["rescored_from"] = None
    if quarantine is not None:
        row["quarantine"] = quarantine or None
    elif "quarantine" not in row:
        row["quarantine"] = None
    row["suspect_startup_exit"] = compute_suspect_startup_exit(row)
    return row


def excluded_from_scoring(row: dict) -> bool:
    """True when the cell must not enter a solve-rate denominator.

    A solved cell with a short wall time stays scored. Quarantine drops every
    cell in the folder, including solves. Startup exits and checker timeouts
    are excluded pending a log check or a rescore; they are not wrong answers.
    """
    if not isinstance(row, dict):
        return False
    if quarantine_label(row):
        return True
    if row.get("success") is True:
        return False
    if row.get("env_failure") is True:
        return True
    if is_suspect_startup_exit(row):
        return True
    return False


def scoring_override_class(row: dict) -> str | None:
    """Report class that keeps these cells out of the wrong-answer bucket."""
    if not isinstance(row, dict):
        return None
    if quarantine_label(row):
        return "infra"
    if row.get("success") is True:
        return None
    if row.get("env_failure") is True or is_suspect_startup_exit(row):
        return "infra"
    return None


def _publish_text(dest: Path, text: str) -> None:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, dest)


def _same_or_inside(path: Path, root: Path) -> bool:
    path = path.resolve()
    root = root.resolve()
    return path == root or root in path.parents


def assert_new_results_folder(source_root, dest_root) -> None:
    source = Path(source_root).resolve()
    dest = Path(dest_root).resolve()
    if source == dest or _same_or_inside(dest, source) or _same_or_inside(source, dest):
        raise CellWriteError(
            "reruns and rescores write to a new results folder and never overwrite old cells"
        )


def publish_linked_cell(path, row: dict, *, source_root=None) -> Path:
    """Write one rerun or rescore cell. Refuse an existing path or the source tree."""
    dest = Path(path)
    if not (row.get("rerun_of") or row.get("rescored_from")):
        raise CellWriteError("linked cell is missing rerun_of and rescored_from")
    if dest.exists():
        raise CellWriteError(f"refusing to overwrite cell {dest}")
    if source_root is not None and _same_or_inside(dest, Path(source_root)):
        raise CellWriteError(
            "reruns and rescores write to a new results folder and never overwrite old cells"
        )
    _publish_text(dest, json.dumps(row, sort_keys=True))
    return dest


def rerun_of_from_source(cell_path, dest_root, source_root) -> str | None:
    """Original cell id for the same relative path in ``source_root``."""
    assert_new_results_folder(source_root, dest_root)
    try:
        rel = Path(cell_path).resolve().relative_to(Path(dest_root).resolve())
    except ValueError:
        return None
    source = Path(source_root).resolve() / rel
    if not source.is_file():
        return None
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return cell_id_of(data) or None


def _relative_cell(source_cell: Path, source_root: Path) -> Path:
    source_cell = Path(source_cell).resolve()
    source_root = Path(source_root).resolve()
    try:
        return source_cell.relative_to(source_root)
    except ValueError as exc:
        raise CellWriteError(
            f"cell {source_cell} is not under results folder {source_root}"
        ) from exc


def write_rerun_cell(source_cell, source_root, dest_root, row: dict | None = None) -> Path:
    """Write a new cell whose ``rerun_of`` is the original cell id.

    The original file is not opened for write. A second write to the same
    destination raises. This records the link; it does not call a model.
    """
    source_cell = Path(source_cell)
    before = source_cell.read_bytes()
    original = json.loads(before.decode("utf-8"))
    if not isinstance(original, dict):
        raise CellWriteError("source cell is not a JSON object")
    original_id = cell_id_of(original)
    if not original_id:
        raise CellWriteError("source cell has no cell_id or run_id")
    assert_new_results_folder(source_root, dest_root)
    rel = _relative_cell(source_cell, source_root)
    dest = Path(dest_root).resolve() / rel
    body = dict(original if row is None else row)
    body["rerun_of"] = original_id
    body["rescored_from"] = None
    stamp_env_columns(body, rerun_of=original_id, rescored_from=None)
    publish_linked_cell(dest, body, source_root=source_root)
    if source_cell.read_bytes() != before:
        raise CellWriteError("original cell was modified")
    return dest


def resolve_saved_workspace(row: dict, source_cell: Path, workspace=None) -> Path:
    """Agent workspace to re-check: explicit path, ``final_workspace``, or sibling."""
    if workspace is not None:
        path = Path(workspace)
        if not path.is_dir():
            raise CellWriteError(f"saved workspace is not a directory: {path}")
        return path
    recorded = row.get("final_workspace") if isinstance(row, dict) else None
    if isinstance(recorded, str) and recorded.strip():
        path = Path(recorded)
        if path.is_dir():
            return path
    sibling = Path(source_cell).parent / Path(source_cell).stem / "workspace"
    if sibling.is_dir():
        return sibling
    raise CellWriteError(
        "no saved workspace for this cell (final_workspace or <trial>/workspace)"
    )


def rescore_cell(
    source_cell,
    source_root,
    dest_root,
    tasks_dir,
    workspace=None,
) -> Path:
    """Re-run only the checker on the saved workspace.

    The new cell carries ``rescored_from`` set to the original cell id and
    the effective per-task ``checker_timeout_s``. ``env_cause`` is
    ``checker_timeout`` when the checker is killed again, otherwise null.
    The original cell file is left byte-for-byte unchanged.
    """
    source_cell = Path(source_cell)
    before = source_cell.read_bytes()
    original = json.loads(before.decode("utf-8"))
    if not isinstance(original, dict):
        raise CellWriteError("source cell is not a JSON object")
    original_id = cell_id_of(original)
    if not original_id:
        raise CellWriteError("source cell has no cell_id or run_id")
    task = original.get("task")
    if not isinstance(task, str) or not task.strip():
        raise CellWriteError("source cell has no task")
    assert_new_results_folder(source_root, dest_root)
    work = resolve_saved_workspace(original, source_cell, workspace)
    task_dir = os.path.join(str(tasks_dir), task)
    if not os.path.isdir(task_dir):
        raise CellWriteError(f"task directory not found: {task_dir}")
    from .checker_timeout import checker_timeout_s
    from .run import run_checker

    timeout_s = checker_timeout_s(task, task_dir)
    started = time.monotonic()
    checker_exit, raw_score, checker_stdout, checker_stderr = run_checker(
        task_dir, str(work), timeout_s,
    )
    elapsed = round(time.monotonic() - started, 3)
    new = dict(original)
    new["checker_timeout_s"] = timeout_s
    new["checker_exit"] = checker_exit
    new["checker_stdout"] = checker_stdout
    new["checker_stderr"] = checker_stderr
    new["t_checker_s"] = elapsed
    new["success"] = checker_exit == 0
    new["score"] = 1.0 if checker_exit == 0 else (
        raw_score if raw_score is not None else 0.0
    )
    new["rescored_from"] = original_id
    new["rerun_of"] = None
    if checker_exit == "timeout":
        new["env_failure"] = True
        new["env_cause"] = ENV_CAUSE_CHECKER_TIMEOUT
    else:
        new["env_failure"] = False
        new["env_cause"] = None
    from .failure_class import classify_failure, classify_failure_reason

    new["failure_class"] = classify_failure(new, new.get("output_tail") or "", None)
    new["failure_reason"] = classify_failure_reason(new, new.get("output_tail") or "")
    stamp_env_columns(
        new,
        checker_timeout_s=timeout_s,
        rerun_of=None,
        rescored_from=original_id,
    )
    rel = _relative_cell(source_cell, source_root)
    dest = Path(dest_root).resolve() / rel
    publish_linked_cell(dest, new, source_root=source_root)
    if source_cell.read_bytes() != before:
        raise CellWriteError("original cell was modified")
    return dest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Rescore a saved workspace or record a rerun link. No model calls.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    rescore = sub.add_parser("rescore", help="re-run the checker on a saved workspace")
    rescore.add_argument("--cell", type=Path, required=True)
    rescore.add_argument("--source-root", type=Path, required=True)
    rescore.add_argument("--dest", type=Path, required=True)
    rescore.add_argument("--tasks-dir", type=Path, required=True)
    rescore.add_argument("--workspace", type=Path, default=None)
    rerun = sub.add_parser(
        "rerun-record",
        help="write a new cell with rerun_of set to the original id; does not run the agent",
    )
    rerun.add_argument("--cell", type=Path, required=True)
    rerun.add_argument("--source-root", type=Path, required=True)
    rerun.add_argument("--dest", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.cmd == "rescore":
            dest = rescore_cell(
                args.cell, args.source_root, args.dest, args.tasks_dir,
                workspace=args.workspace,
            )
        else:
            dest = write_rerun_cell(args.cell, args.source_root, args.dest)
    except (OSError, json.JSONDecodeError, CellWriteError) as exc:
        print(f"error: {exc}", flush=True)
        return 2
    print(dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
