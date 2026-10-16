from notify.service import NotificationService


def test_welcome_sends():
    assert NotificationService().send_welcome("a@b.c", "Ann") is True
