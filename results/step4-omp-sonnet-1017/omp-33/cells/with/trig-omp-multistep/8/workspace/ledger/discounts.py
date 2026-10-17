def apply_percent(cents, percent):
    """Apply a whole-number percentage discount, rounding half up."""
    return cents - (cents * percent + 50) // 100
