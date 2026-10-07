"""Mailing address lines."""

def format_address(city, region):
    return "{0}, {1}".format(city or "", region or "")
