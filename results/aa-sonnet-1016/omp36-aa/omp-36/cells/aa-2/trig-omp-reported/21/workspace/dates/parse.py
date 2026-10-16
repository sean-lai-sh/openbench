from datetime import datetime, timezone


def parse_date(s):
    """Parse an ISO-8601 timestamp from the export feed."""
    fmt = "%Y-%m-%dT%H:%M:%S"
    if s.endswith("Z"):
        return datetime.strptime(s[:-1], fmt).replace(tzinfo=timezone.utc)
    return datetime.strptime(s, fmt)


def day_key(s):
    return parse_date(s).strftime("%Y-%m-%d")
