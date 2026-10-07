"""Billing period bounds."""

def period_key(year, month):
    return "{0}-{1:02d}".format(year, month)
