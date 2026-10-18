"""Money helpers. All internal arithmetic is done in integer cents."""
from decimal import ROUND_HALF_UP, Decimal


def to_cents(amount):
    """Convert a decimal amount like 19.99 to integer cents, rounding half up.

    Goes through str() so the float's shortest repr (19.99) is used rather than
    its binary expansion (19.989999...), which truncation would turn into 1998.
    """
    return int((Decimal(str(amount)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def format_cents(cents):
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100}.{cents % 100:02d}"
