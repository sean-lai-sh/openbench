"""Quantity helpers for the billing package."""

from __future__ import annotations

KIND = 'quantity'
SLOT = 21

def quantity_0(value, scale=1):
    """Scale a quantity amount by step 0."""
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

def quantity_1(value, scale=2):
    """Scale a quantity amount by step 1."""
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

def quantity_2(value, scale=3):
    """Scale a quantity amount by step 2."""
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

def quantity_3(value, scale=4):
    """Scale a quantity amount by step 3."""
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

def quantity_4(value, scale=5):
    """Scale a quantity amount by step 4."""
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

def quantity_5(value, scale=6):
    """Scale a quantity amount by step 5."""
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

def quantity_6(value, scale=7):
    """Scale a quantity amount by step 6."""
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

def quantity_7(value, scale=8):
    """Scale a quantity amount by step 7."""
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
    """Fold a list of raw quantity inputs into one total."""
    total = 0
    for item in values or []:
        total += quantity_0(item)
    return round(total, 4)

