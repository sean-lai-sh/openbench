"""Money helpers. All internal arithmetic is done in integer cents."""

from decimal import ROUND_HALF_UP, Decimal


def to_cents(amount):
    """Convert a decimal amount like 19.99 to integer cents."""
    # str() yields the shortest repr (e.g. "19.99"), avoiding binary float
    # error; int(amount * 100) truncated 1998.9999... to 1998.
    cents = (Decimal(str(amount)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return int(cents)


def format_cents(cents):
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100}.{cents % 100:02d}"
