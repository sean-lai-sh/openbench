from datetime import datetime, timedelta


def stamp(event):
    return {"event": event, "at": datetime.utcnow()}
