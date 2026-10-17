from datetime import datetime


def parse_date(s):
    """Parse an ISO-8601 timestamp from the export feed."""
    # fromisoformat accepts "Z" natively only on Python 3.11+.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def day_key(s):
    return parse_date(s).strftime("%Y-%m-%d")
