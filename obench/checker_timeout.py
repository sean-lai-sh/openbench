"""Per-task checker timeout. One table, three runners.

The historical default is 120 seconds. Checkers that cold-install torch or
other heavy wheels (torch-tensor, torch-pipeline, model-extraction, and
sam-cell-seg) need 600 seconds. ``task.toml`` ``checker_timeout_s`` overrides
the table when a task sets it.
"""

from __future__ import annotations

import os

DEFAULT_CHECKER_TIMEOUT_S = 120
HEAVY_CHECKER_TIMEOUT_S = 600

# Prefix match so ``torch-tensor`` and ``torch-tensor-parallelism`` share a row.
# sam-cell-seg's Harbor checker installs torch, torchvision, and MobileSAM.
HEAVY_CHECKER_PREFIXES = (
    "torch-tensor",
    "torch-pipeline",
    "model-extraction",
    "sam-cell-seg",
)


def task_name_of(task, task_dir=None) -> str:
    """Basename of a task directory, or the task id when no directory is given."""
    if task_dir:
        return os.path.basename(os.path.abspath(str(task_dir)).rstrip(os.sep))
    text = str(task or "").strip().rstrip("/\\")
    if not text:
        return ""
    return os.path.basename(text)


def _timeout_from_toml(task_dir) -> int | None:
    if not task_dir:
        return None
    path = os.path.join(str(task_dir), "task.toml")
    if not os.path.isfile(path):
        return None
    try:
        import tomllib
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except (OSError, ValueError):
        return None
    value = data.get("checker_timeout_s") if isinstance(data, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value <= 0:
        return None
    return int(value)


def _directory_for(task, task_dir):
    if task_dir and os.path.isdir(str(task_dir)):
        return str(task_dir)
    text = str(task or "")
    if text and os.path.isdir(text):
        return text
    return task_dir


def checker_timeout_s(task, task_dir=None) -> int:
    """Effective checker timeout in seconds for one task.

    ``task.toml`` wins, then the heavy-checker table, then 120.
    """
    directory = _directory_for(task, task_dir)
    override = _timeout_from_toml(directory)
    if override is not None:
        return override
    name = task_name_of(task, directory)
    for prefix in HEAVY_CHECKER_PREFIXES:
        if name == prefix or name.startswith(prefix):
            return HEAVY_CHECKER_TIMEOUT_S
    return DEFAULT_CHECKER_TIMEOUT_S


def effective_checker_timeout(task, tasks_dir, override=None) -> int:
    """Resolver for a CLI default.

    An explicit timeout other than the 120-second default replaces the table.
    Leaving the flag at 120 keeps the per-task value.
    """
    task_dir = None
    if tasks_dir and task:
        task_dir = os.path.join(str(tasks_dir), str(task))
    if (
        override is not None
        and not isinstance(override, bool)
        and isinstance(override, (int, float))
        and int(override) != DEFAULT_CHECKER_TIMEOUT_S
        and int(override) > 0
    ):
        return int(override)
    return checker_timeout_s(task, task_dir)
