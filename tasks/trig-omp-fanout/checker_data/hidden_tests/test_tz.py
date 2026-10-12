from datetime import timezone, timedelta
from app import audit, billing, cache, sessions, reports


def aware(d):
    return d.tzinfo is not None and d.utcoffset() == timedelta(0)


def test_all_aware():
    assert aware(audit.stamp("x")["at"])
    assert aware(billing.due_date(1))
    assert aware(cache.Entry(1, 5).expires)
    assert aware(sessions.new_session("u")["created"])
    assert aware(reports.generated_at())
    assert "+00:00" in reports.header("T")
