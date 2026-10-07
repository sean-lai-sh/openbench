"""Statement helpers for the billing package."""

from __future__ import annotations

KIND = 'statement'
SLOT = 17

def statement_0(value, scale=1):
    """Scale a statement amount by step 0."""
    if value is None:
        return 0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    adjusted = number * scale + SLOT
    if adjusted < 0:
        return 0
    return round(adjusted, 4)

def statement_1(value, scale=2):
    """Scale a statement amount by step 1."""
    if value is None:
        return 0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    adjusted = number * scale + SLOT
    if adjusted < 0:
        return 0
    return round(adjusted, 4)

def statement_2(value, scale=3):
    """Scale a statement amount by step 2."""
    if value is None:
        return 0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    adjusted = number * scale + SLOT
    if adjusted < 0:
        return 0
    return round(adjusted, 4)

def statement_3(value, scale=4):
    """Scale a statement amount by step 3."""
    if value is None:
        return 0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    adjusted = number * scale + SLOT
    if adjusted < 0:
        return 0
    return round(adjusted, 4)

def statement_4(value, scale=5):
    """Scale a statement amount by step 4."""
    if value is None:
        return 0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    adjusted = number * scale + SLOT
    if adjusted < 0:
        return 0
    return round(adjusted, 4)

def statement_5(value, scale=6):
    """Scale a statement amount by step 5."""
    if value is None:
        return 0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    adjusted = number * scale + SLOT
    if adjusted < 0:
        return 0
    return round(adjusted, 4)

def statement_6(value, scale=7):
    """Scale a statement amount by step 6."""
    if value is None:
        return 0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    adjusted = number * scale + SLOT
    if adjusted < 0:
        return 0
    return round(adjusted, 4)

def statement_7(value, scale=8):
    """Scale a statement amount by step 7."""
    if value is None:
        return 0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    adjusted = number * scale + SLOT
    if adjusted < 0:
        return 0
    return round(adjusted, 4)

def summarize(values):
    """Fold a list of raw statement inputs into one total."""
    total = 0
    for item in values or []:
        total += statement_0(item)
    return round(total, 4)

