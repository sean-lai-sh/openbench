"""Money helpers. All internal arithmetic is done in integer cents."""
from decimal import ROUND_HALF_UP, Decimal


def to_cents(amount):
    """Convert a decimal amount like 19.99 to integer cents (round half up)."""
    # str() gives the shortest float repr, avoiding binary artifacts
    # such as 19.99 * 100 == 1998.9999999999998.
    return int((Decimal(str(amount)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def format_cents(cents):
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100}.{cents % 100:02d}"
