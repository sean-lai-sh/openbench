from notify.legacy_mailer import LegacyMailer


def _format_legacy(to, subject, body):
    """Old wire format the LegacyMailer expects."""
    return f"TO:{to}\nSUBJ:{subject}\n\n{body}"


class NotificationService:
    def __init__(self, mailer=None):
        self.mailer = mailer or LegacyMailer()

    def send_welcome(self, user_email, name):
        return self.mailer.deliver(_format_legacy(user_email, "Welcome", f"Hi {name}!"))

    def send_reset(self, user_email, token):
        return self.mailer.deliver(_format_legacy(user_email, "Password reset", f"Token: {token}"))
