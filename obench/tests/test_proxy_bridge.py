"""Shared bridge proxy path for Pi and OpenCode.

Unit tests cover the origin rewrite and a forwarder that is not a wildcard
bind. The docker test is skipped when the daemon is down. It does not call a
model and it does not send an HTTP request to api.anthropic.com.
"""

from __future__ import annotations

import ipaddress
import json
import os
import socket
import subprocess
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from obench import docker_exec
from obench.adapters import opencode, pi_harness
from thesis.ab.proxy_bridge import (
    ANTHROPIC_HOST,
    BridgeError,
    BridgeForwarder,
    bridge_egress_command,
    cell_network,
    format_egress_line,
    peer_allowed,
    docker_bridge_gateway,
    proxy_origin_for_network,
    publish_proxy_port,
    read_proxy_observed,
    shared_proxy_port,
)
from thesis.ab.run_ab import bind_cell_proxy
from thesis.ab.vertex_anthropic_proxy import start_proxy

_MARKER = b"bridge-proxy-ok"
_ENV = (
    "BENCH_IN_CONTAINER",
    "OBENCH_DOCKER_NETWORK",
    "OBENCH_VERTEX_PROXY_URL",
    "OBENCH_OPENCODE_PROXY",
    "OBENCH_PI_VERTEX",
    "OBENCH_PI_HARNESS",
    "OBENCH_OPENCODE_BIN",
    "OBENCH_OPENCODE_MOUNT",
    "OPENCODE_NODE_PREFIX",
)


class _Env:
    def __init__(self, **updates):
        self.updates = updates

    def __enter__(self):
        self.saved = {key: os.environ.get(key) for key in self.updates}
        for key, value in self.updates.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        return self

    def __exit__(self, *_exc):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _cleared():
    return {key: None for key in _ENV}


class _MarkerHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self._send(_MARKER)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        body = json.dumps({
            "id": "msg",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "bridge-proxy-ok"}],
            "stop_reason": "end_turn",
            "usage": {
                "input_tokens": 1,
                "output_tokens": 1,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
        }).encode("utf-8")
        self._send(body)

    def _send(self, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return


class SharedOriginTests(unittest.TestCase):
    def test_pi_and_opencode_share_the_bridge_origin(self):
        with _Env(BENCH_IN_CONTAINER="1", OBENCH_DOCKER_NETWORK="bridge"):
            pi_url = pi_harness.rewrite_loopback("http://127.0.0.1:9/c/cell")
            oc_url = opencode.reachable_proxy_base("http://127.0.0.1:9/v1")
        pi_parts = urlsplit(pi_url)
        oc_parts = urlsplit(oc_url)
        self.assertEqual(pi_parts.scheme, oc_parts.scheme)
        self.assertEqual(pi_parts.hostname, oc_parts.hostname)
        self.assertEqual(pi_parts.port, oc_parts.port)
        self.assertEqual(pi_parts.scheme, "http")
        self.assertEqual(pi_parts.hostname, "host.docker.internal")
        self.assertEqual(pi_parts.port, 9)
        self.assertEqual(
            proxy_origin_for_network("http://127.0.0.1:9/v1", "bridge"),
            oc_url,
        )

    def test_host_network_keeps_loopback_for_both_adapters(self):
        with _Env(BENCH_IN_CONTAINER="1", OBENCH_DOCKER_NETWORK="host"):
            self.assertEqual(
                pi_harness.rewrite_loopback("http://127.0.0.1:9/c/cell"),
                "http://127.0.0.1:9/c/cell",
            )
            self.assertEqual(
                opencode.reachable_proxy_base("http://127.0.0.1:9/v1"),
                "http://127.0.0.1:9/v1",
            )
        self.assertEqual(proxy_origin_for_network("http://127.0.0.1:9", "local"), "http://127.0.0.1:9")
        self.assertEqual(proxy_origin_for_network("http://127.0.0.1:9", "host"), "http://127.0.0.1:9")

    def test_batch_cell_gives_both_harnesses_the_same_origin(self):
        body = json.dumps({"providers": {"vertex-anthropic": {"baseUrl": "http://127.0.0.1:9"}}})
        filled = bind_cell_proxy({
            "exec_mode": "docker",
            "proxy": {"base_url": "http://127.0.0.1:9/v1", "model_ref": "anthropic/claude-opus-5-5"},
            "config": {"provider": {"anthropic": {"options": {"baseURL": "http://127.0.0.1:9/v1"}}}},
            "vertex": {"proxy_url": "http://127.0.0.1:9", "models_body": body},
        }, Path("/tmp/ledger"))
        opencode_url = urlsplit(filled["proxy"]["base_url"])
        pi_url = urlsplit(filled["vertex"]["proxy_url"])
        self.assertEqual(
            (opencode_url.scheme, opencode_url.hostname, opencode_url.port),
            (pi_url.scheme, pi_url.hostname, pi_url.port),
        )
        self.assertEqual(opencode_url.hostname, "host.docker.internal")
        self.assertEqual(opencode_url.port, 9)
        self.assertTrue(filled["proxy"]["base_url"].endswith("/v1"))
        self.assertNotIn("/v1", filled["vertex"]["proxy_url"])
        parsed = json.loads(filled["vertex"]["models_body"])
        self.assertEqual(
            parsed["providers"]["vertex-anthropic"]["baseUrl"],
            filled["vertex"]["proxy_url"],
        )
        self.assertEqual(
            filled["config"]["provider"]["anthropic"]["options"]["baseURL"],
            filled["proxy"]["base_url"],
        )

    def test_host_network_batch_cell_stays_on_loopback(self):
        body = json.dumps({"providers": {"vertex-anthropic": {"baseUrl": "http://127.0.0.1:9"}}})
        filled = bind_cell_proxy({
            "exec_mode": "docker",
            "docker_args": ["--network=host"],
            "proxy": {"base_url": "http://127.0.0.1:9/v1"},
            "vertex": {"proxy_url": "http://127.0.0.1:9", "models_body": body},
        }, Path("/tmp/ledger"))
        self.assertTrue(filled["proxy"]["base_url"].startswith("http://127.0.0.1:9/c/"))
        self.assertTrue(filled["vertex"]["proxy_url"].startswith("http://127.0.0.1:9/c/"))
        self.assertNotIn("host.docker.internal", filled["proxy"]["base_url"])
        self.assertEqual(cell_network("local", ["--network", "host"]), "local")
        self.assertEqual(cell_network("docker", ["--net", "host"]), "host")
        self.assertEqual(cell_network("docker", None), "bridge")

    def test_shared_port_rejects_a_split_listener(self):
        same = _cleared()
        same.update({
            "OBENCH_VERTEX_PROXY_URL": "http://127.0.0.1:9",
            "OBENCH_OPENCODE_PROXY": json.dumps({"base_url": "http://127.0.0.1:9/v1"}),
        })
        with _Env(**same):
            self.assertEqual(shared_proxy_port(), 9)
        split = _cleared()
        split.update({
            "OBENCH_VERTEX_PROXY_URL": "http://127.0.0.1:9",
            "OBENCH_OPENCODE_PROXY": json.dumps({"base_url": "http://127.0.0.1:10/v1"}),
        })
        with _Env(**split):
            with self.assertRaises(BridgeError):
                shared_proxy_port()

    def test_docker_argv_is_the_same_publication_for_both_harnesses(self):
        pi_env = _cleared()
        pi_env.update({
            "OBENCH_PI_HARNESS": "1",
            "OBENCH_VERTEX_PROXY_URL": "http://127.0.0.1:9",
        })
        oc_env = _cleared()
        oc_env["OBENCH_OPENCODE_PROXY"] = json.dumps({
            "model_ref": "anthropic/claude-opus-5-5",
            "base_url": "http://127.0.0.1:9/v1",
        })
        kwargs = dict(
            workdir="/tmp/wd", model="claude-sonnet-5-5", timeout_s=60,
            adapters_dir="/repo/obench/adapters", image="openbench-harness:latest",
            instruction_path="/tmp/instr",
        )
        with _Env(**pi_env):
            pi_cmd = docker_exec.build_docker_cmd(harness="pi", **kwargs)
        with _Env(**oc_env):
            oc_cmd = docker_exec.build_docker_cmd(harness="opencode", **kwargs)
        for cmd in (pi_cmd, oc_cmd):
            self.assertIn("--add-host=host.docker.internal:host-gateway", cmd)
            self.assertIn("--add-host=api.anthropic.com:0.0.0.0", cmd)
            self.assertIn("OBENCH_DOCKER_NETWORK=bridge", cmd)
        with _Env(**pi_env):
            host_cmd = docker_exec.build_docker_cmd(
                harness="pi", extra_docker_args=["--network", "host"], **kwargs,
            )
        self.assertNotIn("--add-host=host.docker.internal:host-gateway", host_cmd)
        self.assertNotIn("api.anthropic.com", " ".join(host_cmd))

    def test_opencode_binary_and_node_mount_at_the_wrapper_paths(self):
        with tempfile.TemporaryDirectory() as root:
            cache = Path(root) / "h1" / "opencode-src"
            node = Path(root) / "h1" / "toolchain" / "node-v20.19.2-linux-x64"
            binary = cache / "bin" / "abc" / "opencode"
            binary.parent.mkdir(parents=True)
            binary.write_text("#!/bin/sh\n", encoding="utf-8")
            node.mkdir(parents=True)
            updates = _cleared()
            updates["OBENCH_OPENCODE_PROXY"] = json.dumps({
                "model_ref": "anthropic/claude-opus-5-5",
                "base_url": "http://127.0.0.1:9/v1",
            })
            updates["OBENCH_OPENCODE_BIN"] = str(binary)
            updates["OBENCH_OPENCODE_MOUNT"] = str(cache)
            updates["OPENCODE_NODE_PREFIX"] = str(node)
            with _Env(**updates):
                cmd = docker_exec.build_docker_cmd(
                    harness="opencode", workdir="/tmp/wd", model="claude-opus-5-5",
                    timeout_s=60, adapters_dir="/repo/obench/adapters",
                    image="h1-env:1027-strace", instruction_path="/tmp/instr",
                )
        self.assertIn(f"{os.path.abspath(cache)}:/h1/opencode-src:ro", cmd)
        self.assertIn(
            f"{os.path.abspath(node)}:/h1/toolchain/node-v20.19.2-linux-x64:ro",
            cmd,
        )
        self.assertIn("OBENCH_OPENCODE_BIN=/h1/opencode-src/bin/abc/opencode", cmd)
        self.assertIn(
            "PATH=/h1/toolchain/node-v20.19.2-linux-x64/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            cmd,
        )
        self.assertIn("OBENCH_DOCKER_NETWORK=bridge", cmd)

    def test_opencode_bridge_cell_requires_an_image(self):
        import importlib.util
        path = Path(__file__).resolve().parents[2] / "data" / "opencode-harness-smoke" / "cell.py"
        spec = importlib.util.spec_from_file_location("opencode_bridge_cell", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with _Env(OBENCH_CELL_IMAGE=None):
            with self.assertRaises(SystemExit) as caught:
                module.main([
                    "--out", "/tmp/oc-bridge-no-image", "--exec", "docker", "--sha", "a" * 40,
                ])
        self.assertIn("image", str(caught.exception))

    def test_proxy_observed_reads_thinking_and_reasoning(self):
        ledger = Path(tempfile.mkdtemp())
        self.assertEqual(read_proxy_observed(ledger, "cell"), [])
        (ledger / "cell.jsonl").write_text(
            json.dumps({
                "record_type": "request",
                "thinking_mode": "default",
                "thinking_sent": "adaptive",
                "usage": {"reasoning_tokens": 12, "output_tokens": 20},
            }) + "\n",
            encoding="utf-8",
        )
        self.assertEqual(read_proxy_observed(ledger, "cell"), [{
            "thinking_mode": "default",
            "thinking_sent": "adaptive",
            "reasoning_tokens": 12,
        }])


class ForwarderTests(unittest.TestCase):
    def test_non_bridge_peer_is_refused(self):
        network = ipaddress.ip_network("172.17.0.0/16")
        self.assertTrue(peer_allowed("172.17.0.4", network))
        self.assertTrue(peer_allowed("127.0.0.1", network))
        self.assertFalse(peer_allowed("203.0.113.5", network))
        self.assertFalse(peer_allowed("172.18.0.2", network))
        self.assertFalse(peer_allowed("203.0.113.5", network, allow_loopback=False))
        self.assertFalse(peer_allowed("not-an-ip", network))

    def test_wildcard_bind_is_refused(self):
        with self.assertRaises(BridgeError):
            publish_proxy_port(9, gateway="0.0.0.0", subnet="0.0.0.0/0")

    def test_forwarder_relays_on_its_address_and_nowhere_else(self):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _MarkerHandler)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        forwarder = publish_proxy_port(port, gateway="127.0.0.2", subnet="127.0.0.0/8")
        self.addCleanup(forwarder.close)
        self.assertEqual(forwarder.listen_address, ("127.0.0.2", port))
        self.assertNotEqual(forwarder.listen_address[0], "0.0.0.0")
        with urllib.request.urlopen(f"http://127.0.0.2:{port}/health", timeout=3) as resp:
            self.assertIn(_MARKER, resp.read())
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as resp:
            self.assertIn(_MARKER, resp.read())
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.3", port), timeout=0.5)

    def test_disallowed_source_does_not_receive_the_proxy_body(self):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _MarkerHandler)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        forwarder = BridgeForwarder.listen(
            "127.0.0.2",
            port,
            ("127.0.0.1", port),
            ipaddress.ip_network("10.0.0.0/8"),
            allow_loopback=False,
        )
        self.addCleanup(forwarder.close)
        client = socket.create_connection(("127.0.0.2", port), timeout=2)
        self.addCleanup(client.close)
        client.settimeout(2)
        try:
            client.sendall(b"GET / HTTP/1.0\r\n\r\n")
            data = client.recv(128)
        except OSError:
            data = b""
        self.assertNotIn(_MARKER, data)

    def test_start_proxy_stays_on_loopback_until_published(self):
        proxy = start_proxy("proj", token="tok", upstream="http://127.0.0.1:1")
        self.addCleanup(proxy.close)
        port = proxy._httpd.server_address[1]
        self.assertTrue(proxy.base_url.startswith("http://127.0.0.1:"))
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.2", port), timeout=0.5)

    def test_egress_probe_sinkholes_and_does_not_request_anthropic(self):
        cmd = bridge_egress_command("img:latest")
        self.assertIn(f"{ANTHROPIC_HOST}:0.0.0.0", cmd)
        self.assertIn("--network", cmd)
        self.assertEqual(cmd[cmd.index("--network") + 1], "bridge")
        script = cmd[-1]
        self.assertNotIn("https://api.anthropic.com", script)
        self.assertNotIn("http://api.anthropic.com", script)
        self.assertIn("getaddrinfo", script)
        self.assertEqual(
            format_egress_line(True, "sinkhole 0.0.0.0"),
            "egress api.anthropic.com blocked (sinkhole 0.0.0.0)",
        )
        self.assertIn("REACHABLE", format_egress_line(False, "10.0.0.1"))


def _docker_ready() -> bool:
    try:
        proc = subprocess.run(["docker", "info"], capture_output=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def _python_image() -> str | None:
    try:
        proc = subprocess.run(
            ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    names = [line.strip() for line in (proc.stdout or "").splitlines() if ":" in line]
    preferred = (
        "python:3.12-alpine", "python:3.11-alpine",
        "python:3.12-slim", "python:3.11-slim",
    )
    for name in preferred:
        if name in names:
            return name
    for name in names:
        if name.startswith("python:"):
            return name
    try:
        pull = subprocess.run(
            ["docker", "pull", "python:3.12-alpine"],
            capture_output=True, text=True, timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if pull.returncode != 0:
        return None
    return "python:3.12-alpine"


def _host_ipv4() -> list[str]:
    try:
        proc = subprocess.run(
            ["ip", "-4", "-o", "addr", "show"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    found = []
    for line in (proc.stdout or "").splitlines():
        parts = line.split()
        if "inet" not in parts:
            continue
        found.append(parts[parts.index("inet") + 1].split("/")[0])
    return found


@unittest.skipUnless(_docker_ready(), "docker daemon not available")
class BridgeContainerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = _python_image()
        if not cls.image:
            raise unittest.SkipTest("no python image for the bridge probe")

    def test_bridge_container_reaches_proxy_and_outside_address_does_not(self):
        upstream = ThreadingHTTPServer(("127.0.0.1", 0), _MarkerHandler)
        upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        upstream_thread.start()
        self.addCleanup(upstream.shutdown)
        self.addCleanup(upstream.server_close)
        host, up_port = upstream.server_address
        ledger = Path(tempfile.mkdtemp())
        proxy = start_proxy(
            "proj", token="tok", upstream=f"http://{host}:{up_port}", ledger_dir=ledger,
        )
        self.addCleanup(proxy.close)
        forwarder = proxy.publish_on_docker_bridge()
        self.assertIsNotNone(forwarder.listen_address)
        listen_host, port = forwarder.listen_address
        self.assertNotEqual(listen_host, "0.0.0.0")
        self.assertEqual(port, proxy._httpd.server_address[1])
        self.assertTrue(proxy.base_url.startswith("http://127.0.0.1:"))

        bridge_net = ipaddress.ip_network(docker_bridge_gateway()[1], strict=False)
        outside = [
            addr for addr in _host_ipv4()
            if addr != listen_host and ipaddress.ip_address(addr) not in bridge_net
            and not ipaddress.ip_address(addr).is_loopback
        ]
        # A host with only loopback and the docker bridge still refuses a
        # non-bridge peer in ForwarderTests. When another address exists,
        # connecting to it must fail and a packet sourced from it must not
        # receive the proxy body.
        for addr in outside:
            with self.assertRaises(OSError):
                socket.create_connection((addr, port), timeout=1)
            client = socket.socket()
            client.settimeout(2)
            try:
                client.bind((addr, 0))
                try:
                    client.connect((listen_host, port))
                except OSError:
                    data = b""
                else:
                    try:
                        client.sendall(b"POST /v1/messages HTTP/1.0\r\nContent-Length: 2\r\n\r\n{}")
                        data = client.recv(256)
                    except OSError:
                        data = b""
                self.assertNotIn(_MARKER, data)
            finally:
                client.close()

        script = (
            "import json, socket, urllib.request\n"
            "infos = socket.getaddrinfo('api.anthropic.com', 443)\n"
            "addrs = sorted({item[4][0] for item in infos})\n"
            "print('anthropic ' + ','.join(addrs))\n"
            f"url = 'http://host.docker.internal:{port}/c/bridgecell/v1/messages'\n"
            "body = json.dumps({'messages': [{'role': 'user', 'content': 'ping'}]}).encode()\n"
            "req = urllib.request.Request(url, data=body, headers={'content-type': 'application/json'})\n"
            "with urllib.request.urlopen(req, timeout=10) as resp:\n"
            "    print(resp.read().decode())\n"
        )
        proc = subprocess.run(
            [
                "docker", "run", "--rm", "--network", "bridge",
                "--add-host=host.docker.internal:host-gateway",
                "--add-host=api.anthropic.com:0.0.0.0",
                self.image, "python3", "-c", script,
            ],
            capture_output=True, text=True, timeout=60,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        self.assertEqual(proc.returncode, 0, output)
        self.assertIn("bridge-proxy-ok", output)
        self.assertIn("anthropic 0.0.0.0", output)
        self.assertNotIn("https://api.anthropic.com", output)
        self.assertTrue(proxy.reached("bridgecell"))
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/c/hostcell/v1/messages",
            data=b'{"messages":[{"role":"user","content":"ping"}]}',
            timeout=5,
        ) as resp:
            self.assertIn(b"bridge-proxy-ok", resp.read())


if __name__ == "__main__":
    unittest.main()
