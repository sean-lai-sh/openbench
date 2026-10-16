"""Deprecated transport. Only NotificationService uses it."""


class LegacyMailer:
    def __init__(self):
        self.outbox = []

    def deliver(self, raw):
        self.outbox.append(raw)
        return True
