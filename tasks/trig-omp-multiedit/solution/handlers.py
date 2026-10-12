"""Request handlers for the profile service."""


_STORE = {}


def _normalize(user_id):
    return user_id.strip().lower()


def get_profile(user_id):
    """Get profile."""
    if not user_id or not str(user_id).strip():
        raise ValueError("user_id must not be empty")
    key = _normalize(user_id)
    record = _STORE.get(key)
    if record is None:
        return None
    result = {
        "id": key,
        "name": record.get("name"),
        "orders": len(record.get("orders", [])),
    }
    return result


def update_profile(user_id, **fields):
    """Update profile."""
    if not user_id or not str(user_id).strip():
        raise ValueError("user_id must not be empty")
    key = _normalize(user_id)
    record = _STORE.setdefault(key, {"orders": []})
    for field, value in fields.items():
        if value is None:
            continue
        record[field] = value
    result = {
        "id": key,
        "updated": sorted(fields),
    }
    return result


def delete_profile(user_id):
    """Delete profile."""
    if not user_id or not str(user_id).strip():
        raise ValueError("user_id must not be empty")
    key = _normalize(user_id)
    if key not in _STORE:
        return None
    _STORE.pop(key)
    result = {
        "id": key,
        "deleted": True,
    }
    return result


def list_orders(user_id, limit=None):
    """List orders."""
    if not user_id or not str(user_id).strip():
        raise ValueError("user_id must not be empty")
    key = _normalize(user_id)
    record = _STORE.get(key)
    if record is None:
        return None
    orders = list(record.get("orders", []))
    if limit is not None:
        orders = orders[:limit]
    result = {
        "id": key,
        "orders": orders,
    }
    return result


def add_order(user_id, order):
    """Add order."""
    if not user_id or not str(user_id).strip():
        raise ValueError("user_id must not be empty")
    key = _normalize(user_id)
    record = _STORE.setdefault(key, {"orders": []})
    record["orders"].append(order)
    result = {
        "id": key,
        "count": len(record["orders"]),
    }
    return result


def _reset():
    _STORE.clear()
