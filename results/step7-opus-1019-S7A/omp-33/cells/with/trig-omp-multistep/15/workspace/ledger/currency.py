"""Money helpers. All internal arithmetic is done in integer cents."""

from decimal import ROUND_HALF_UP, Decimal


def to_cents(amount):
    """Convert a decimal amount like 19.99 to integer cents, rounding half up."""
    # str() yields the shortest repr (19.99, not 19.989999...), so binary float
    # error never leaks into the cent value.
    return int((Decimal(str(amount)) * 100).to_integral_value(ROUND_HALF_UP))


def format_cents(cents):
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100}.{cents % 100:02d}"
