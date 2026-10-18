from pricing.money import split


def test_split():
    assert split(10.00, 3) == [3.34, 3.33, 3.33]
