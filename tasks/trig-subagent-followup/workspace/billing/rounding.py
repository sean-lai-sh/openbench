"""Money rounding."""

def money(value):
    return round(float(value or 0), 2)
