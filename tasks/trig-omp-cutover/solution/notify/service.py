from notify.smtp_client import SmtpClient


class NotificationService:
    def __init__(self, client=None):
        self.client = client or SmtpClient()

    def send_welcome(self, user_email, name):
        return self.client.send(to=user_email, subject="Welcome", body=f"Hi {name}!")

    def send_reset(self, user_email, token):
        return self.client.send(to=user_email, subject="Password reset", body=f"Token: {token}")
