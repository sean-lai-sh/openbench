"""HTTP access layer (stubbed for tests)."""
_FAKE = {}


def _get(url, timeout):
    return _FAKE.get(url, f"body:{url}:{timeout}")


def legacy_fetch(url, timeout=5):
    # legacy_fetch is kept for old callers; prefer fetch_v2.
    return _get(url, timeout)


def fetch_v2(url, timeout=5):
    return _get(url, timeout)
