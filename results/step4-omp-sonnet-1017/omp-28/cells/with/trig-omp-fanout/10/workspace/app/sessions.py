from datetime import datetime, timedelta, timezone


def new_session(user):
    now = datetime.now(timezone.utc)
    return {"user": user, "created": now, "last_seen": now}
