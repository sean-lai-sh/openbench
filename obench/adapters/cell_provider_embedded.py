"""In-cell copy of ``obench.provider_embedded``. Stdlib only.

The docker cell does not install the ``obench`` package. The adapter loads
this sibling when ``obench.provider_embedded`` is not importable.
"""

from __future__ import annotations

import os
import re

_PKG = "@ai-sdk/anthropic"
_BUN_PATH = re.compile(
    rb"node_modules/\.bun/@ai-sdk\+anthropic@([0-9][0-9A-Za-z.\-]*)\+?[^/\s]*"
    rb"/node_modules/@ai-sdk/anthropic/dist/index\.mjs")
_FLAT_PATH = re.compile(rb"node_modules/@ai-sdk/anthropic/dist/index\.mjs")
_VERSION_VAR = re.compile(rb'var VERSION\d* = "([0-9][0-9A-Za-z.\-]*)"')
_CACHE: dict[tuple, str] = {}


def scan(data: bytes) -> str:
    """Return the bundled ``@ai-sdk/anthropic`` version in ``data``, or ''."""
    found = {m.group(1).decode() for m in _BUN_PATH.finditer(data)}
    if len(found) == 1:
        return found.pop()
    if len(found) > 1:
        return ""  # ambiguous: more than one bundled copy
    m = _FLAT_PATH.search(data)
    if m:
        v = _VERSION_VAR.search(data, m.end(), m.end() + 4096)
        if v:
            return v.group(1).decode()
    return ""


def embedded_version(binary: str) -> str:
    """Bundled ``@ai-sdk/anthropic`` version in ``binary``, or '' if none."""
    try:
        st = os.stat(binary)
    except OSError:
        return ""
    key = (os.path.realpath(binary), st.st_size, st.st_mtime_ns)
    if key not in _CACHE:
        try:
            with open(binary, "rb") as fh:
                _CACHE[key] = scan(fh.read())
        except OSError:
            _CACHE[key] = ""
    return _CACHE[key]
