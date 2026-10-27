"""Which route a cell's model requests took.

compat picks one of two ways to point the stock anthropic provider at the
proxy: ``provider options`` (baseURL in config) or ``ANTHROPIC_BASE_URL``.
Both are now always set, so a flaky ``models`` probe cannot leave a cell with
only the env var, which some builds ignore at ``run`` time (3251/without and
0dc80df6 both sent a request to api.anthropic.com that way).

``route`` is ``on:<how>`` when at least one request reached the expected
endpoint (the per-cell proxy ledger, or the readiness stub) and
``off:<how>`` when none did. An off-route cell is infra: not scored, rerun.
"""

HOWS = {"provider options": "provider-options", "ANTHROPIC_BASE_URL": "base-url-env"}


def how_of(proxy) -> str:
    if not isinstance(proxy, dict):
        return "none"
    how = str(proxy.get("route") or "")
    if how in HOWS:
        return HOWS[how]
    return how or "unknown"


def route_label(proxy, reached: int | None) -> str:
    """``reached`` counts requests that hit the expected endpoint."""
    return ("on:" if reached else "off:") + how_of(proxy)


def off_route(row) -> bool:
    return isinstance(row, dict) and str(row.get("route") or "").startswith("off:")
