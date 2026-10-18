"""Money helpers. All internal arithmetic is done in integer cents."""
from decimal import ROUND_HALF_UP, Decimal


def to_cents(amount):
    """Convert a decimal amount like 19.99 to integer cents, rounding half up.

    Goes through str() so 19.99 is read as the decimal 19.99, not the binary
    float 19.989999...; int() truncation would lose a cent.
    """
    return int((Decimal(str(amount)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def format_cents(cents):
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100}.{cents % 100:02d}"
