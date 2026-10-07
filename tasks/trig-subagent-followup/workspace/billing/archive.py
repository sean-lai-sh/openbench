"""Closed-period archive stamps."""

def stamp(year, month):
    return "closed-{0}-{1:02d}".format(year, month)
