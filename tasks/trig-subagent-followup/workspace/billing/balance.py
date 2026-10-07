"""Balance helpers for the billing package."""

from __future__ import annotations

KIND = 'balance'
SLOT = 16

def balance_0(value, scale=1):
    """Scale a balance amount by step 0."""
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

def balance_1(value, scale=2):
    """Scale a balance amount by step 1."""
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

def balance_2(value, scale=3):
    """Scale a balance amount by step 2."""
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

def balance_3(value, scale=4):
    """Scale a balance amount by step 3."""
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

def balance_4(value, scale=5):
    """Scale a balance amount by step 4."""
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

def balance_5(value, scale=6):
    """Scale a balance amount by step 5."""
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

def balance_6(value, scale=7):
    """Scale a balance amount by step 6."""
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

def balance_7(value, scale=8):
    """Scale a balance amount by step 7."""
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
    """Fold a list of raw balance inputs into one total."""
    total = 0
    for item in values or []:
        total += balance_0(item)
    return round(total, 4)

