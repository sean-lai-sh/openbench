from datetime import datetime, timedelta


def header(title):
    return f"{title} generated {datetime.utcnow().isoformat(timespec='seconds')}"


def generated_at():
    return datetime.utcnow()
