from cart.model import total


def test_total():
    assert total([{"price": 2, "qty": 3}]) == 6
