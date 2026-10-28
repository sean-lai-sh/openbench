"""Load a sibling of an adapter by file path. Stdlib only.

Docker cells mount ``obench/adapters`` at ``/bench/adapters``. They do not
install the ``obench`` or ``thesis`` packages, so an adapter cannot import
those names. ``prefer`` uses the host package when it is importable and the
sibling file when it is not.
"""

from __future__ import annotations

import importlib.util
import os
import sys


def load(anchor: str, filename: str, qualname: str):
    """Execute ``filename`` next to ``anchor`` and cache it as ``qualname``."""
    cached = sys.modules.get(qualname)
    if cached is not None:
        return cached
    path = os.path.join(os.path.dirname(os.path.abspath(anchor)), filename)
    spec = importlib.util.spec_from_file_location(qualname, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualname] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(qualname, None)
        raise
    return module


def prefer(anchor: str, filename: str, qualname: str, importer):
    """Return ``importer()``, or the sibling module if that import fails."""
    try:
        return importer()
    except ImportError:
        return load(anchor, filename, qualname)
