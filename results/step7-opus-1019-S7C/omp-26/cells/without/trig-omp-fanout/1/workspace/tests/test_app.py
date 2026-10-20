from datetime import timedelta
from app import audit, billing, cache, sessions, reports


def test_audit():
    assert audit.stamp("x")["event"] == "x"


def test_billing():
    assert billing.due_date(3) > billing.due_date(1)


def test_cache():
    e = cache.Entry(1, 3600)
    assert not e.expired()
    assert cache.Entry(1, -1).expired()


def test_sessions():
    s = sessions.new_session("u")
    assert s["created"] == s["last_seen"]


def test_reports():
    assert reports.header("T").startswith("T generated ")
