from datetime import datetime, timedelta


class Entry:
    def __init__(self, value, ttl_s):
        self.value = value
        self.expires = datetime.utcnow() + timedelta(seconds=ttl_s)

    def expired(self):
        return datetime.utcnow() >= self.expires
