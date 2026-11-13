"""The one place the reflection loop's pass cutoff lives (SEA-106).

A task *passes* for a model when the model's pass rate over its trials is at
or above ``PASS_CUTOFF``. Change it here, nowhere else; every swap decision and
report reads it through ``pass_cutoff()``.
"""

from __future__ import annotations

import os

PASS_CUTOFF = 0.90
CUTOFF_ENV = "OBENCH_HARD_PASS_CUTOFF"  # one-off override for a run; recorded in the swap log


def pass_cutoff() -> float:
    """``PASS_CUTOFF``, or ``OBENCH_HARD_PASS_CUTOFF`` when set (0 < x <= 1)."""
    raw = os.environ.get(CUTOFF_ENV, "").strip()
    if not raw:
        return PASS_CUTOFF
    value = float(raw)
    if not 0.0 < value <= 1.0:
        raise ValueError(f"{CUTOFF_ENV}={raw!r} is not in (0, 1]")
    return value
