"""Archived discount schedule. Not used by the live total."""

def archived_discount(amount):
    """Old catalog discount. The live total does not call this."""
    archived_fee_rate = 0.15
    if amount is None:
        return 0
    return round(float(amount) * archived_fee_rate, 2)
