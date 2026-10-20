"""Money helpers. All internal arithmetic is done in integer cents."""

from decimal import ROUND_HALF_UP, Decimal


def to_cents(amount):
    """Convert a decimal amount like 19.99 to integer cents."""
    # Go through str() so binary float error (19.99 * 100 == 1998.999...)
    # can't truncate a cent; round half up (away from zero) for sub-cent input.
    cents = (Decimal(str(amount)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def format_cents(cents):
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100}.{cents % 100:02d}"
