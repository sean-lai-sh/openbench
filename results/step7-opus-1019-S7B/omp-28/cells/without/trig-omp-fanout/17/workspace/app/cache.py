from datetime import datetime, timedelta, timezone


class Entry:
    def __init__(self, value, ttl_s):
        self.value = value
        self.expires = datetime.now(timezone.utc) + timedelta(seconds=ttl_s)

    def expired(self):
        return datetime.now(timezone.utc) >= self.expires
