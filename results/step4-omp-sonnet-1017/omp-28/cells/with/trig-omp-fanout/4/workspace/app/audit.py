from datetime import datetime, timedelta, timezone


def stamp(event):
    return {"event": event, "at": datetime.now(timezone.utc)}
