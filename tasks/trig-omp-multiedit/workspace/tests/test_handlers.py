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
