"""A Python with no installed obench, for checker subprocesses."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

_BIN: Path | None = None


def bare_python_bin() -> Path:
    """venv ``bin`` whose ``python3`` cannot see a pip-installed obench."""
    global _BIN
    if _BIN is None:
        root = Path(tempfile.mkdtemp(prefix="obench-bare-py-"))
        subprocess.check_call(
            [sys.executable, "-m", "venv", "--without-pip", str(root)],
            stdout=subprocess.DEVNULL,
        )
        _BIN = root / "bin"
    return _BIN


def checker_environ(base: dict | None = None) -> dict:
    """Environment for checker.sh: PYTHONPATH unset, python has no obench."""
    env = dict(os.environ if base is None else base)
    env.pop("PYTHONPATH", None)
    env["PYTHONNOUSERSITE"] = "1"
    env["PATH"] = str(bare_python_bin()) + os.pathsep + env.get("PATH", "")
    return env
