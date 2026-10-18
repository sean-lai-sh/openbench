from datetime import datetime, timezone


def parse_date(s):
    """Parse an ISO-8601 timestamp from the export feed.

    A trailing "Z" yields a UTC-aware datetime; no suffix yields a naive one.
    """
    if s.endswith("Z"):
        return datetime.strptime(s[:-1], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")


def day_key(s):
    return parse_date(s).strftime("%Y-%m-%d")
