from .currency import to_cents


class Line:
    def __init__(self, sku, unit_price, qty=1):
        self.sku = sku
        self.unit_price = unit_price
        self.qty = qty

    def cents(self):
        return to_cents(self.unit_price) * self.qty
