"""Money helpers. All internal arithmetic is done in integer cents."""


def to_cents(amount):
    """Convert a decimal amount like 19.99 to integer cents."""
    return round(amount * 100)


def format_cents(cents):
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100}.{cents % 100:02d}"
