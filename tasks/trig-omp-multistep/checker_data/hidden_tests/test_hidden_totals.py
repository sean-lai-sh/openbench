from ledger.lines import Line
from ledger.totals import invoice_total, subtotal


def test_subtotal_single():
    assert subtotal([Line("A1", 19.99)]) == 1999


def test_subtotal_qty():
    assert subtotal([Line("B2", 0.29, qty=3)]) == 87


def test_total_with_tax():
    assert invoice_total([Line("A1", 10.00)], state="CA") == 1073


def test_total_discount():
    assert invoice_total([Line("C3", 4.35, qty=2)], discount_percent=10) == 783


def test_more_prices():
    for price, cents in [(0.07, 7), (1.15, 115), (2.675, 268), (99.99, 9999), (0.57, 57)]:
        assert subtotal([Line("X", price)]) == cents, price
