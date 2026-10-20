from datetime import datetime, timedelta, timezone


def header(title):
    return f"{title} generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}"


def generated_at():
    return datetime.now(timezone.utc)
