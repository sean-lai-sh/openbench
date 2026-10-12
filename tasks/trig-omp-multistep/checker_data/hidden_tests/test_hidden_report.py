from ledger.currency import format_cents
from ledger.report import render
from ledger.lines import Line


def test_format():
    assert format_cents(1234) == "$12.34"


def test_render():
    assert render([Line("A1", 19.99)]).endswith("TOTAL $19.99")
