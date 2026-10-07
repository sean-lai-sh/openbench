"""Product sku helpers."""

def sku(family, n):
    return "{0}-{1:03d}".format(family, n)
