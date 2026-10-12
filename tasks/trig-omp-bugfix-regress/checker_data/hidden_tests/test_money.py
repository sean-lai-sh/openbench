from pricing.money import split


def test_split():
    assert split(10.00, 3) == [3.34, 3.33, 3.33]


from pricing.money import round_money, add_vat


def test_round_money():
    assert round_money(2.675) == 2.68
    assert round_money(1.005) == 1.01
    assert round_money(0.125) == 0.13
    assert round_money(2.674) == 2.67
    assert round_money(10) == 10.0
    assert round_money(-1.005) == -1.01


def test_vat():
    assert add_vat(10.0) == 12.0
