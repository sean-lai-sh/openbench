from datetime import timezone
from dates.parse import parse_date, day_key


def test_dates():
    d = parse_date("2026-10-12T08:30:00Z")
    assert (d.year, d.month, d.day, d.hour, d.minute) == (2026, 10, 12, 8, 30)


def test_naive():
    assert parse_date("2026-01-02T03:04:05").hour == 3


def test_day_key():
    assert day_key("2026-10-12T23:59:59") == "2026-10-12"
