"""Loopback rewrite for a bridge-network cell. Stdlib only.

The docker cell mounts ``obench/adapters`` and ``entry.py``. It does not mount
``thesis``. Pi and OpenCode both call this module from the adapter process, so
it must stay importable when ``thesis`` is not.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
CONTAINER_HOST = "host.docker.internal"
_TRUTHY_NETWORKS = frozenset({"host", "bridge", "local"})


def runtime_network() -> str:
    """Network of the process that is about to open the proxy.

    ``OBENCH_DOCKER_NETWORK`` is set by the cell container. A container that
    does not say otherwise is bridge: that is ``docker run``'s default, and
    host-network runs set the variable to ``host``.
    """
    explicit = os.environ.get("OBENCH_DOCKER_NETWORK", "").strip().lower()
    if explicit in _TRUTHY_NETWORKS:
        return explicit
    if os.environ.get("BENCH_IN_CONTAINER"):
        return "bridge"
    return "local"


def proxy_origin_for_network(url: str, network: str) -> str:
    """Shared origin for Pi and OpenCode.

    ``local`` and ``host`` keep the URL. ``bridge`` rewrites a loopback host
    to ``host.docker.internal`` and keeps the scheme, port, and path. A URL
    that is already that name, or any non-loopback host, is unchanged.
    """
    text = (url or "").strip()
    if network != "bridge" or not text:
        return text
    parts = urlsplit(text)
    if parts.hostname not in LOOPBACK_HOSTS:
        return text
    port = f":{parts.port}" if parts.port else ""
    user = ""
    if parts.username:
        user = parts.username
        if parts.password is not None:
            user += f":{parts.password}"
        user += "@"
    netloc = f"{user}{CONTAINER_HOST}{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def origin_for_this_process(url: str) -> str:
    """Rewrite ``url`` for the network this process is running on."""
    return proxy_origin_for_network(url, runtime_network())
