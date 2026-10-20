"""Money helpers. All internal arithmetic is done in integer cents."""

from decimal import ROUND_HALF_UP, Decimal


def to_cents(amount):
    """Convert a decimal amount like 19.99 to integer cents."""
    # Go through str() so floats like 19.99 are read as their shortest decimal
    # repr rather than their binary approximation (1998.999... cents), then
    # round half-up instead of truncating.
    cents = Decimal(str(amount)) * 100
    return int(cents.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def format_cents(cents):
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100}.{cents % 100:02d}"
