from datetime import datetime, timedelta


def new_session(user):
    now = datetime.utcnow()
    return {"user": user, "created": now, "last_seen": now}
