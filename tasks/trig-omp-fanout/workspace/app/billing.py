from datetime import datetime, timedelta


def due_date(days):
    return datetime.utcnow() + timedelta(days=days)
