from datetime import datetime


def parse_date(s):
    """Parse an ISO-8601 timestamp from the export feed.

    A trailing ``Z`` or ``±HH:MM`` offset yields an aware datetime; otherwise naive.
    """
    return datetime.fromisoformat(s)


def day_key(s):
    return parse_date(s).strftime("%Y-%m-%d")
