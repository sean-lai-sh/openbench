import handlers as h


def setup_function():
    h._reset()


def test_roundtrip():
    h.update_profile("Ann", name="Ann")
    h.add_order("ann", {"sku": 1})
    assert h.get_profile("ANN") == {"id": "ann", "name": "Ann", "orders": 1}
    assert h.list_orders("ann", limit=5)["orders"] == [{"sku": 1}]
    assert h.delete_profile("ann") == {"id": "ann", "deleted": True}
    assert h.get_profile("ann") is None


import pytest

CALLS = [
    lambda u: h.get_profile(u),
    lambda u: h.update_profile(u, name="x"),
    lambda u: h.delete_profile(u),
    lambda u: h.list_orders(u),
    lambda u: h.add_order(u, {"sku": 2}),
]


@pytest.mark.parametrize("call", CALLS)
@pytest.mark.parametrize("bad", ["", "   "])
def test_empty_rejected(call, bad):
    with pytest.raises(ValueError):
        call(bad)
    assert h._STORE == {}


def test_missing_still_none():
    assert h.get_profile("nobody") is None
    assert h.delete_profile("nobody") is None
    assert h.list_orders("nobody") is None
