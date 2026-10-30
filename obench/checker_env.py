"""Checker environment guards for H2 cells.

Three jobs, all fail-closed:

* ``verify_checker_venv``: before the checker runs, the task's prebuilt venv
  under ``H2_CHECKER_VENV_ROOT`` must exist, its interpreter must resolve and
  run, and its Python version must match the ``# python:`` pin in
  ``thesis/ab/h2env/requirements/<task>.txt``. Otherwise the cell is an env
  failure. Nothing is installed.
* ``classify_checker_output``: a nonzero checker whose output shows an
  infrastructure fault (disk full, dependency download failure, the venv
  fallback path, or an explicit ``OBENCH_ENV_FAILURE:`` marker) is an env
  failure, never ``wrong_answer``.
* ``free_disk_gb`` / ``check_free_disk``: free space is recorded on every cell
  and a cell below the floor stops before the agent runs (no model spend).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

ENV_CAUSE_VENV_MISSING = "checker_venv_missing"
ENV_CAUSE_VENV_MISMATCH = "checker_venv_mismatch"
ENV_CAUSE_ENOSPC = "checker_enospc"
ENV_CAUSE_DOWNLOAD = "checker_dependency_download"
ENV_CAUSE_VENV_BYPASSED = "checker_venv_bypassed"
ENV_CAUSE_LOW_DISK = "low_disk"

MARKER = "OBENCH_ENV_FAILURE:"
MIN_FREE_ENV = "OBENCH_MIN_FREE_DISK_GB"
DEFAULT_MIN_FREE_GB = 15.0
REQUIREMENTS_DIR = (
    Path(__file__).resolve().parent.parent / "thesis" / "ab" / "h2env" / "requirements"
)

_MARKER_RE = re.compile(re.escape(MARKER) + r"\s*([A-Za-z0-9_]+)")
_ENOSPC_RE = re.compile(r"No space left on device|os error 28|\bENOSPC\b", re.IGNORECASE)
_DOWNLOAD_RE = re.compile(
    r"Failed to download|Failed to fetch|Failed to prepare distributions"
    r"|Could not fetch URL|Could not find a version that satisfies"
    r"|Temporary failure in name resolution|Could not resolve host"
    r"|ReadTimeoutError|ConnectTimeoutError|curl: \(\d+\)",
)
# Lines only the uvx fallback in a harbor test.sh prints. With the split
# checker venvs configured, reaching that fallback means the venv was bypassed.
_FALLBACK_RE = re.compile(
    r"^downloading uv \d|^everything's installed!|^\s*Downloading torch\b",
    re.MULTILINE,
)


class CheckerEnvError(RuntimeError):
    """The checker environment is not the pinned one. Never scored."""

    def __init__(self, cause: str, detail: str):
        super().__init__(f"{cause}: {detail}")
        self.cause = cause
        self.detail = detail


def _header(path: Path, key: str) -> str | None:
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split(None, 2)
        if len(parts) >= 3 and parts[0] == "#" and parts[1] == f"{key}:":
            return parts[2].strip()
    return None


def _version_matches(actual: str, pin: str) -> bool:
    actual_parts = actual.strip().split(".")
    pin_parts = pin.strip().split(".")
    return actual_parts[: len(pin_parts)] == pin_parts


def verify_checker_venv(root, task: str, req_dir=None, probe=True) -> Path | None:
    """Return the task's venv python, or None if the task has no prebuilt venv.

    Raises ``CheckerEnvError`` when the venv is missing, its interpreter does
    not resolve or run, or its version differs from the pin.
    """
    req = Path(req_dir or REQUIREMENTS_DIR) / f"{task}.txt"
    if not req.is_file():
        return None
    venv = Path(root) / task
    py = venv / "bin" / "python"
    if not venv.is_dir():
        raise CheckerEnvError(ENV_CAUSE_VENV_MISSING, f"no venv directory {venv}")
    if not (os.path.exists(py) and os.access(py, os.X_OK)):
        target = os.readlink(py) if os.path.islink(py) else None
        detail = f"{py} does not resolve" + (f" (symlink to {target})" if target else "")
        raise CheckerEnvError(ENV_CAUSE_VENV_MISSING, detail)
    pin = _header(req, "python")
    cfg = venv / "pyvenv.cfg"
    cfg_version = None
    if cfg.is_file():
        for line in cfg.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "version_info":
                cfg_version = value.strip()
    if pin and cfg_version and not _version_matches(cfg_version, pin):
        raise CheckerEnvError(
            ENV_CAUSE_VENV_MISMATCH, f"{venv} is Python {cfg_version}, pin is {pin}",
        )
    if probe:
        try:
            proc = subprocess.run(
                [str(py), "-c",
                 "import sys, pytest; print('%d.%d.%d' % sys.version_info[:3])"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CheckerEnvError(ENV_CAUSE_VENV_MISSING, f"{py} did not run: {exc}") from exc
        if proc.returncode != 0:
            tail = (proc.stdout or "").strip().splitlines()[-1:] or [""]
            raise CheckerEnvError(
                ENV_CAUSE_VENV_MISMATCH, f"{py} cannot import pytest: {tail[0]}",
            )
        actual = (proc.stdout or "").strip().splitlines()[-1]
        if pin and not _version_matches(actual, pin):
            raise CheckerEnvError(
                ENV_CAUSE_VENV_MISMATCH, f"{py} runs Python {actual}, pin is {pin}",
            )
    return py


def classify_checker_output(checker_exit, stdout, stderr, split_enabled=False) -> str | None:
    """env_cause for a failed checker whose output shows an infra fault, else None."""
    if checker_exit == 0 or checker_exit == "timeout":
        return None
    text = f"{stdout or ''}\n{stderr or ''}"
    marker = _MARKER_RE.search(text)
    if marker:
        return marker.group(1)
    if _ENOSPC_RE.search(text):
        return ENV_CAUSE_ENOSPC
    if _DOWNLOAD_RE.search(text):
        return ENV_CAUSE_DOWNLOAD
    if split_enabled and _FALLBACK_RE.search(text):
        return ENV_CAUSE_VENV_BYPASSED
    return None


def free_disk_gb(path) -> float | None:
    try:
        return round(shutil.disk_usage(str(path)).free / 1e9, 2)
    except OSError:
        return None


def min_free_gb(split_enabled: bool) -> float | None:
    raw = os.environ.get(MIN_FREE_ENV, "").strip()
    if raw:
        return float(raw)
    return DEFAULT_MIN_FREE_GB if split_enabled else None


def check_free_disk(path, floor_gb) -> float | None:
    """Record free space at ``path``; raise when it is under ``floor_gb``."""
    free = free_disk_gb(path)
    if floor_gb is not None and free is not None and free < floor_gb:
        raise CheckerEnvError(
            ENV_CAUSE_LOW_DISK, f"{free} GB free at {path}, floor is {floor_gb} GB",
        )
    return free


def mark_env_failure(row: dict, cause: str, detail: str) -> dict:
    """Unscored env failure. Never ``wrong_answer``."""
    row["env_failure"] = True
    row["env_cause"] = cause
    row["failure_class"] = "infra"
    row["failure_reason"] = detail
    row["success"] = False
    row["score"] = 0.0
    return row


def verify_split_checker_venv(checker_root, task_dir) -> Path | None:
    """Fail closed for a split-venv checker: the root must exist and verify."""
    task = os.path.basename(os.path.normpath(str(task_dir)))
    if checker_root is None:
        raise CheckerEnvError(ENV_CAUSE_VENV_MISSING, "checker venv stage is not attached")
    return verify_checker_venv(checker_root, task)
