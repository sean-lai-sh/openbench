"""Coarse class of a row's ``pin_source``: override, manifest, lockfile or bundled.

``pin_source`` keeps the detailed manifest evidence (``box_cache``,
``nearest_box_build``, ...). ``pin_source_class`` says which mechanism set the pin.
"""
from __future__ import annotations

CLASSES = ("override", "manifest", "lockfile", "bundled")


def pin_source_class(source) -> str:
    source = str(source or "").strip()
    if not source:
        return ""
    if source in ("override", "env_override"):
        return "override"
    if source == "lockfile":
        return "lockfile"
    if source.startswith("bundled"):
        return "bundled"
    return "manifest"


def stamp(row, source) -> None:
    """Set ``pin_source_class`` on ``row`` from ``source`` when it resolves."""
    klass = pin_source_class(source)
    if klass and isinstance(row, dict):
        row["pin_source_class"] = klass
