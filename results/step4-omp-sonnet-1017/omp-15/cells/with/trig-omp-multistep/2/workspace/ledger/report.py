from .currency import format_cents
from .totals import invoice_total


def render(lines, state="OR"):
    rows = [f"{l.sku:<10}{l.qty:>4}" for l in lines]
    rows.append(f"TOTAL {format_cents(invoice_total(lines, state))}")
    return "\n".join(rows)
