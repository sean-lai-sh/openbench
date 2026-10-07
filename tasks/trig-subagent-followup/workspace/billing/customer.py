"""Customer display names."""

def display_name(first, last):
    return "{0} {1}".format(first or "", last or "").strip()
