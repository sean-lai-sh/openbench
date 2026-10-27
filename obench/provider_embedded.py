"""Read the provider SDK version compiled into an OpenCode binary.

Some builds bundle ``@ai-sdk/anthropic`` into the binary instead of loading
it from ``node_modules`` at run time. strace sees no package open for those,
so the version comes from the bundle itself. Bun leaves a source comment per
module, and the bun install layout puts the version in that path::

    // ../../node_modules/.bun/@ai-sdk+anthropic@2.0.58+d6123d32/node_modules/@ai-sdk/anthropic/dist/index.mjs

With a flat ``node_modules`` layout the path has no version, so this falls
back to the first ``var VERSIONn = "x"`` after that module's comment.
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
