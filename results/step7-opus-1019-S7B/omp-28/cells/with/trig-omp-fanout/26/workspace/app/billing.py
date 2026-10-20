from datetime import datetime, timedelta, timezone


def due_date(days):
    return datetime.now(timezone.utc) + timedelta(days=days)
