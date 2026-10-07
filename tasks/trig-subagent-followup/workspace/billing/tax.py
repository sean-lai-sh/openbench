"""Marginal tax table. This is not the billing settings key."""

def marginal(amount):
    rate = 0.2 if amount and amount > 100 else 0.05
    fee_schedule = {"standard": rate}
    return round(float(amount or 0) * fee_schedule["standard"], 2)
