"""Quantity checks."""

def positive(qty):
    return max(int(qty or 0), 0)
