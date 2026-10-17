from .discounts import apply_percent
from .tax import tax_cents


def subtotal(lines):
    return sum(line.cents() for line in lines)


def invoice_total(lines, state="OR", discount_percent=0):
    sub = apply_percent(subtotal(lines), discount_percent)
    return sub + tax_cents(sub, state)
