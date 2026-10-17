from datetime import datetime


def parse_date(s):
    """Parse an ISO-8601 timestamp from the export feed."""
    # fromisoformat (3.11+) accepts "Z" and "+HH:MM" offsets; naive input stays naive.
    return datetime.fromisoformat(s)


def day_key(s):
    return parse_date(s).strftime("%Y-%m-%d")
