from ledger.currency import format_cents


def test_format():
    assert format_cents(1234) == "$12.34"
    assert format_cents(-5) == "-$0.05"
