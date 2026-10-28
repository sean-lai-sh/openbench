"""One proxy path for every harness on a bridge-networked cell.

The Vertex proxy listens on ``127.0.0.1`` only. That is the host-network and
local path, and it stays that way. A bridge container cannot open that
address via ``host.docker.internal`` (Docker maps the name at the bridge
gateway). This module publishes one TCP forwarder on that gateway, on the
proxy's port, and rewrites loopback origins to ``host.docker.internal`` for
Pi and OpenCode through the same function.

The forwarder binds the gateway address, never ``0.0.0.0``. Peers that are
not on the bridge subnet and not loopback are dropped, so an address outside
the VM cannot use the port. Host OUTPUT rules for ``api.anthropic.com`` are
not touched. Bridge cells additionally sinkhole that name to ``0.0.0.0``,
the container half of ``thesis/ab/launchers/egress_block.sh``.
"""

from __future__ import annotations

import errno
import ipaddress
import json
import os
import socket
import subprocess
import threading
from pathlib import Path
from urllib.parse import urlsplit

from obench.adapters.proxy_loopback import (
    CONTAINER_HOST,
    LOOPBACK_HOSTS,
    proxy_origin_for_network,
    runtime_network,
)

ANTHROPIC_HOST = "api.anthropic.com"
ANTHROPIC_SINKHOLE = "0.0.0.0"
_LOCK = threading.Lock()
_FORWARDERS: dict[int, "BridgeForwarder"] = {}


class BridgeError(RuntimeError):
    pass


def container_network_name(docker_args: list[str] | None = None) -> str:
    """Docker network a cell joins. Unset means the default bridge."""
    return _docker_network_name(docker_args) or "bridge"


def cell_network(exec_mode: str, docker_args: list[str] | None = None) -> str:
    """``local``, ``host``, or ``bridge``.

    Docker's default network is the bridge. ``--network host`` is the
    host-network path and does not rewrite the proxy origin.
    """
    if exec_mode != "docker":
        return "local"
    name = _docker_network_name(docker_args)
    if name == "host":
        return "host"
    return "bridge"


def reachable_proxy_port(url: str) -> int | None:
    """Port of a loopback or bridge-published proxy URL. Others are ignored."""
    parts = urlsplit((url or "").strip())
    host = parts.hostname
    if host not in LOOPBACK_HOSTS and host != CONTAINER_HOST:
        return None
    if parts.port is None:
        return None
    return int(parts.port)


def _urls_from_env() -> list[str]:
    found: list[str] = []
    direct = os.environ.get("OBENCH_VERTEX_PROXY_URL", "").strip()
    if direct:
        found.append(direct)
    for name in ("OBENCH_OPENCODE_PROXY", "OBENCH_PI_VERTEX"):
        raw = os.environ.get(name, "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        for key in ("base_url", "proxy_url"):
            value = str(data.get(key) or "").strip()
            if value:
                found.append(value)
    return found


def shared_proxy_port() -> int | None:
    """The one port Pi and OpenCode must share, or None when no cell proxy is set."""
    ports: list[int] = []
    for url in _urls_from_env():
        port = reachable_proxy_port(url)
        if port is not None:
            ports.append(port)
    unique = set(ports)
    if not unique:
        return None
    if len(unique) != 1:
        raise BridgeError(
            "Pi and OpenCode must share one proxy port, "
            f"got {sorted(unique)}"
        )
    return next(iter(unique))


def peer_allowed(ip: str, network: ipaddress.IPv4Network, *, allow_loopback: bool = True) -> bool:
    """True for the container bridge and, by default, loopback.

    Any other source is outside the VM's container network and is refused.
    """
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address):
        mapped = getattr(addr, "ipv4_mapped", None)
        if mapped is None:
            return bool(allow_loopback and addr.is_loopback)
        addr = mapped
    if allow_loopback and addr.is_loopback:
        return True
    return addr in network


def docker_bridge_gateway(network: str = "bridge") -> tuple[str, str]:
    """IPv4 ``(gateway, subnet)`` for the network ``host-gateway`` points at."""
    try:
        proc = subprocess.run(
            ["docker", "network", "inspect", network, "--format", "{{json .IPAM.Config}}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BridgeError(f"cannot inspect docker network {network}: {exc}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise BridgeError(f"cannot inspect docker network {network}: {detail}")
    try:
        configs = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise BridgeError(f"docker network {network} returned no IPAM config") from exc
    if not isinstance(configs, list):
        raise BridgeError(f"docker network {network} returned no IPAM config")
    for item in configs:
        if not isinstance(item, dict):
            continue
        gateway = str(item.get("Gateway") or "")
        subnet = str(item.get("Subnet") or "")
        if ":" in gateway or not gateway or not subnet:
            continue
        return gateway, subnet
    raise BridgeError(f"docker network {network} has no IPv4 gateway")


class BridgeForwarder:
    """TCP forwarder bound to one address. ``close`` is idempotent."""

    def __init__(self, sock: socket.socket | None, port: int, *, owns_socket: bool):
        self._sock = sock
        self.port = port
        self.owns_socket = owns_socket
        self._closed = sock is None
        self._thread: threading.Thread | None = None
        self.network: ipaddress.IPv4Network | None = None
        self.allow_loopback = True
        self.target: tuple[str, int] = ("127.0.0.1", port)

    @property
    def listen_address(self) -> tuple[str, int] | None:
        if self._sock is None:
            return None
        host, port = self._sock.getsockname()[:2]
        return str(host), int(port)

    @classmethod
    def listen(
        cls,
        host: str,
        port: int,
        target: tuple[str, int],
        network: ipaddress.IPv4Network,
        *,
        allow_loopback: bool = True,
    ) -> "BridgeForwarder":
        if host in {"0.0.0.0", "::", ""}:
            raise BridgeError("refusing to bind the proxy forwarder on a wildcard address")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind((host, port))
            sock.listen(128)
            sock.settimeout(0.5)
        except OSError as exc:
            sock.close()
            if exc.errno == errno.EADDRINUSE:
                return cls(None, port, owns_socket=False)
            raise BridgeError(f"cannot bind {host}:{port}: {exc}") from exc
        fwd = cls(sock, port, owns_socket=True)
        fwd.network = network
        fwd.allow_loopback = allow_loopback
        fwd.target = target
        fwd._thread = threading.Thread(target=fwd._accept_loop, name=f"obench-bridge-{port}", daemon=True)
        fwd._thread.start()
        return fwd

    def close(self) -> None:
        if not self.owns_socket or self._closed:
            self._closed = True
            return
        self._closed = True
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        with _LOCK:
            if _FORWARDERS.get(self.port) is self:
                _FORWARDERS.pop(self.port, None)

    def _accept_loop(self) -> None:
        while not self._closed:
            sock = self._sock
            if sock is None:
                return
            try:
                client, addr = sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            peer = addr[0] if addr else ""
            if self.network is None or not peer_allowed(
                peer, self.network, allow_loopback=self.allow_loopback
            ):
                client.close()
                continue
            threading.Thread(
                target=_relay, args=(client, self.target), daemon=True,
            ).start()


def _relay(client: socket.socket, target: tuple[str, int]) -> None:
    upstream: socket.socket | None = None
    try:
        upstream = socket.create_connection(target, timeout=10)
        upstream.settimeout(None)
        client.settimeout(None)
        left = threading.Thread(target=_pipe, args=(client, upstream), daemon=True)
        right = threading.Thread(target=_pipe, args=(upstream, client), daemon=True)
        left.start()
        right.start()
        left.join()
        right.join()
    except OSError:
        pass
    finally:
        for sock in (client, upstream):
            if sock is None:
                continue
            try:
                sock.close()
            except OSError:
                pass


def _pipe(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            chunk = src.recv(65536)
            if not chunk:
                break
            dst.sendall(chunk)
    except OSError:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def publish_proxy_port(
    port: int,
    *,
    gateway: str | None = None,
    subnet: str | None = None,
    allow_loopback: bool = True,
    network_name: str = "bridge",
) -> BridgeForwarder:
    """Listen on the bridge gateway at ``port`` and forward to ``127.0.0.1:port``.

    A second call in this process returns the forwarder it already owns. If
    another process already bound the port, the handle does not own the socket
    and ``close`` does not tear it down.
    """
    with _LOCK:
        current = _FORWARDERS.get(port)
        if current is not None and current.owns_socket and not current._closed:
            return current
    if gateway is None or subnet is None:
        gateway, subnet = docker_bridge_gateway(network_name)
    if gateway in {"0.0.0.0", "::", ""}:
        raise BridgeError("refusing to bind the proxy forwarder on a wildcard address")
    try:
        network = ipaddress.ip_network(subnet, strict=False)
    except ValueError as exc:
        raise BridgeError(f"bridge subnet {subnet!r} is not a network") from exc
    if not isinstance(network, ipaddress.IPv4Network):
        raise BridgeError("bridge forwarder only publishes the IPv4 gateway")
    gateway_addr = ipaddress.ip_address(gateway)
    if not isinstance(gateway_addr, ipaddress.IPv4Address):
        raise BridgeError("bridge forwarder only publishes the IPv4 gateway")
    if gateway_addr not in network and not gateway_addr.is_loopback:
        raise BridgeError("bridge gateway is outside its subnet")
    fwd = BridgeForwarder.listen(
        gateway,
        port,
        ("127.0.0.1", port),
        network,
        allow_loopback=allow_loopback,
    )
    if fwd.owns_socket:
        with _LOCK:
            _FORWARDERS[port] = fwd
    return fwd


def ensure_forwarder_from_env(network_name: str = "bridge") -> BridgeForwarder | None:
    """Publish the shared port when the environment names a loopback proxy."""
    port = shared_proxy_port()
    if port is None:
        return None
    return publish_proxy_port(port, network_name=network_name)


def reasoning_tokens(usage: dict | None) -> int | None:
    """Reasoning tokens the proxy stored on one request, if the provider sent them."""
    if not isinstance(usage, dict):
        return None
    for key in ("reasoning_tokens", "reasoning_output_tokens", "reasoning"):
        value = usage.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        return int(value)
    details = usage.get("output_tokens_details")
    if isinstance(details, dict):
        value = details.get("reasoning_tokens")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return int(value)
    return None


def proxy_observed_settings(records: list | None) -> list[dict]:
    """Thinking and reasoning the proxy recorded for each request.

    ``thinking_mode`` is the proxy's pin. ``thinking_sent`` is the ``thinking``
    field it classified on the request. ``reasoning_tokens`` is the provider
    usage field when one was present.
    """
    observed = []
    for record in records or []:
        if not isinstance(record, dict):
            continue
        if record.get("record_type") not in {None, "request"}:
            continue
        usage = record.get("usage") if isinstance(record.get("usage"), dict) else {}
        observed.append({
            "thinking_mode": record.get("thinking_mode"),
            "thinking_sent": record.get("thinking_sent"),
            "reasoning_tokens": reasoning_tokens(usage),
        })
    return observed


def read_proxy_observed(ledger_dir, cell_id: str) -> list[dict]:
    """Settings from the cell's ledger. An empty ledger is an empty list."""
    from thesis.ab.vertex_anthropic_proxy import cell_ledger_path

    path = cell_ledger_path(Path(ledger_dir), cell_id)
    if not path.is_file():
        return []
    records = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            records.append(item)
    return proxy_observed_settings(records)


def format_egress_line(blocked: bool, detail: str) -> str:
    state = "blocked" if blocked else "REACHABLE"
    text = " ".join((detail or "").split())
    return f"egress {ANTHROPIC_HOST} {state} ({text})"


_EGRESS_PROBE = """
import socket
host = "api.anthropic.com"
try:
    infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
except OSError as exc:
    print("blocked resolve %s" % type(exc).__name__)
    raise SystemExit(0)
addrs = sorted({item[4][0] for item in infos})
if addrs and all(addr in {"0.0.0.0", "::", "::0"} for addr in addrs):
    print("blocked sinkhole %s" % ",".join(addrs))
    raise SystemExit(0)
target = addrs[0]
sock = socket.socket()
sock.settimeout(3)
try:
    sock.connect((target, 443))
except OSError as exc:
    print("blocked connect %s %s" % (target, type(exc).__name__))
    raise SystemExit(0)
finally:
    sock.close()
print("REACHABLE %s" % target)
raise SystemExit(1)
"""


def bridge_egress_command(image: str) -> list[str]:
    """Container argv that sinkholes ``api.anthropic.com`` and does not request it.

    The probe only resolves the name and, if that is not the sinkhole, tries a
    TCP connect. It never sends an HTTP request to Anthropic.
    """
    return [
        "docker", "run", "--rm", "--network", "bridge",
        "--add-host", f"{ANTHROPIC_HOST}:{ANTHROPIC_SINKHOLE}",
        image, "python3", "-c", _EGRESS_PROBE,
    ]


def bridge_egress_probe(image: str, runner=None) -> str:
    """One smoke line. ``blocked`` means the cell network has no direct route."""
    cmd = bridge_egress_command(image)
    run = runner or _default_egress_runner
    returncode, output = run(cmd)
    blocked = returncode == 0 and "REACHABLE" not in output
    detail = " ".join(output.split()) or f"exit {returncode}"
    return format_egress_line(blocked, detail)


def _default_egress_runner(cmd: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return proc.returncode, ((proc.stdout or "") + (proc.stderr or "")).strip()


def _docker_network_name(args: list[str] | None) -> str | None:
    if not args:
        return None
    for index, arg in enumerate(args):
        if arg in {"--network", "--net"} and index + 1 < len(args):
            return args[index + 1]
        if arg.startswith("--network=") or arg.startswith("--net="):
            return arg.split("=", 1)[1]
    return None
