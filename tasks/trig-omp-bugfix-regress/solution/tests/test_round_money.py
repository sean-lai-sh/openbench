from pricing.money import round_money


def test_half_up_regression():
    assert round_money(2.675) == 2.68
