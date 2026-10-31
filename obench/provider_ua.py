"""The ``@ai-sdk/anthropic`` version a request actually came from.

The AI SDK stamps every provider request with a User-Agent suffix
``ai-sdk/anthropic/<version>``. That string is built from the SDK copy that
made the call, so it names the loaded SDK even when the binary bundles its
own copy and ignores the pinned ``node_modules``. The proxy records it per
request as ``loaded_anthropic``; rows carry the per-cell aggregate.
"""
from __future__ import annotations

import re
from typing import Iterable

_UA = re.compile(r"ai-sdk/anthropic/([0-9][0-9A-Za-z.\-]*)")


def loaded_anthropic_from_ua(user_agent) -> str:
    """Version in an ``ai-sdk/anthropic/X`` User-Agent, or ''."""
    if not isinstance(user_agent, str):
        return ""
    found = {m.group(1).rstrip(".-") for m in _UA.finditer(user_agent)}
    return found.pop() if len(found) == 1 else ""


def aggregate(values: Iterable) -> str:
    """One cell's value from its requests: the version, '' if none was seen,
    or ``mixed:a,b`` when requests disagree (never equal to a pin)."""
    seen = sorted({v for v in values if isinstance(v, str) and v})
    if not seen:
        return ""
    return seen[0] if len(seen) == 1 else "mixed:" + ",".join(seen)
