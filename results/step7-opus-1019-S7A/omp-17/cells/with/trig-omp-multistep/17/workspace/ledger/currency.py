"""Money helpers. All internal arithmetic is done in integer cents."""

from decimal import ROUND_HALF_UP, Decimal


def to_cents(amount):
    """Convert a decimal amount like 19.99 to integer cents.

    Floats are converted via their shortest repr (str) so binary
    representation error (19.99 * 100 == 1998.999...) cannot truncate a
    cent. Sub-cent amounts round half up (away from zero).
    """
    if isinstance(amount, float):
        amount = str(amount)
    return int((Decimal(amount) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def format_cents(cents):
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100}.{cents % 100:02d}"
