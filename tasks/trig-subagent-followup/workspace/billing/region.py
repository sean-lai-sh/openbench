"""Region codes."""

def region_code(name):
    return (name or "xx")[:2].upper()
