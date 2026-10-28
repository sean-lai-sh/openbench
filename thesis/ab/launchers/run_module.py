"""Run a module from the launcher checkout, not from the process cwd.

The F03-2 launcher is often started with cwd=~/ob-f032, the pinned runner.
``python -m`` and ``python -c`` put that directory first on ``sys.path``, ahead
of ``PYTHONPATH``, and import the runner's ``thesis`` package. That package has
no ``step8_project``. This file is started by path (so cwd is not ``sys.path[0]``)
and then inserts the launcher repo root first. It exits if the imported
``thesis`` is not this checkout or has no ``step8_project``.

Usage: python3 run_module.py <module> [args...]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def install() -> str:
    """Put the launcher repo root first on ``sys.path``. Return that root."""
    root = str(REPO)
    script_dir = str(Path(__file__).resolve().parent)
    cleaned = []
    for entry in sys.path:
        if entry in ("", ".", script_dir, root):
            continue
        cleaned.append(entry)
    sys.path[:] = [root, *cleaned]
    return root


def main(argv: list[str]) -> None:
    if not argv:
        raise SystemExit("usage: run_module.py <module> [args...]")
    root = install()
    import thesis
    origin = Path(getattr(thesis, "__file__", "") or "").resolve()
    if not str(origin).startswith(root + os.sep):
        raise SystemExit(f"imported thesis from {origin}, not the launcher checkout {root}")
    module = argv[0]
    try:
        imported = __import__(module, fromlist=["*"])
    except ImportError as exc:
        raise SystemExit(f"launcher checkout {root} lacks {module} ({origin}): {exc}") from exc
    loaded = Path(getattr(imported, "__file__", "") or "").resolve()
    if not str(loaded).startswith(root + os.sep):
        raise SystemExit(f"{module} loaded from {loaded}, not the launcher checkout {root}")
    if module != "thesis.ab.step8_project":
        try:
            __import__("thesis.ab.step8_project")
        except ImportError as exc:
            raise SystemExit(f"launcher thesis at {origin} lacks step8_project: {exc}") from exc
    # Execute as __main__ so the module's CLI runs. Drop the import above so
    # runpy does not reuse a module whose __name__ is not __main__.
    sys.modules.pop(module, None)
    sys.argv = list(argv)
    import runpy
    runpy.run_module(module, run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main(sys.argv[1:])
