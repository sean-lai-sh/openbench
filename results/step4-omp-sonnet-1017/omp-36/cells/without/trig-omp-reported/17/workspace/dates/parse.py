from datetime import datetime


def parse_date(s):
    """Parse an ISO-8601 timestamp from the export feed."""
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")


def day_key(s):
    return parse_date(s).strftime("%Y-%m-%d")
