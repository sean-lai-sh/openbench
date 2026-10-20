"""HTTP access layer (stubbed for tests)."""
_FAKE = {}


def _get(url, timeout):
    return _FAKE.get(url, f"body:{url}:{timeout}")


def fetch_v2(url, timeout=5):
    return _get(url, timeout)
