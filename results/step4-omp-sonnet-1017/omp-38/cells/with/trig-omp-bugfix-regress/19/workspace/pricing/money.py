from decimal import Decimal, ROUND_HALF_UP


def round_money(x):
    """Round a price to cents, half up (customer-facing)."""
    # str() gives the shortest repr (2.675 -> '2.675'), avoiding binary-float error.
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def add_vat(x, rate=0.2):
    return round_money(x * (1 + rate))


def split(total, n):
    base = int(total * 100) // n
    parts = [base] * n
    for i in range(int(round(total * 100)) - base * n):
        parts[i] += 1
    return [p / 100 for p in parts]
