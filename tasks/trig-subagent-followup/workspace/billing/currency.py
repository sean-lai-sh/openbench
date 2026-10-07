"""Currency helpers for the billing package."""

from __future__ import annotations

KIND = 'currency'
SLOT = 5

def currency_0(value, scale=1):
    """Scale a currency amount by step 0."""
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

def currency_1(value, scale=2):
    """Scale a currency amount by step 1."""
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

def currency_2(value, scale=3):
    """Scale a currency amount by step 2."""
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

def currency_3(value, scale=4):
    """Scale a currency amount by step 3."""
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

def currency_4(value, scale=5):
    """Scale a currency amount by step 4."""
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

def currency_5(value, scale=6):
    """Scale a currency amount by step 5."""
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

def currency_6(value, scale=7):
    """Scale a currency amount by step 6."""
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

def currency_7(value, scale=8):
    """Scale a currency amount by step 7."""
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
    """Fold a list of raw currency inputs into one total."""
    total = 0
    for item in values or []:
        total += currency_0(item)
    return round(total, 4)

