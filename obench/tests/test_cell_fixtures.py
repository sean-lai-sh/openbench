"""Per-PR fixture options, context-limit override, and proxy fault injection."""

from __future__ import annotations

import json
import struct
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from thesis.ab.cell_fixtures import (
    IMAGE_MODALITIES,
    NAMED_COLOURS,
    PNG_SIDE,
    WEBFETCH_PLACEHOLDER,
    FixtureError,
    apply_context_limit,
    apply_image_modalities,
    bind_local_webfetch,
    colour_for_seed,
    compaction_overflow,
    compaction_usable,
    parse_options,
    png_for_colour,
)
from thesis.ab.compat import anthropic_proxy_config
from thesis.ab.run_ab import _fill, apply_cell_meter
from thesis.ab.summarize import row_cost
from thesis.ab.vertex_anthropic_proxy import ProxyError, cell_bytes_path, start_proxy


class OptionParseTests(unittest.TestCase):
    def test_blank_options_are_empty(self):
        parsed = parse_options("  ")
        self.assertIsNone(parsed.context)
        self.assertEqual(parsed.as_text(), "")
        self.assertFalse(parsed.payload()["global_agents"])

    def test_known_options_round_trip(self):
        parsed = parse_options(
            "context=72000; fault=sse-server-error; mode=plan; "
            "permissions=workspace; global-agents=1; lsp=pyright,typescript; "
            "modalities=image; webfetch=local; disable-tools=bash,write"
        )
        self.assertEqual(parsed.context, 72000)
        self.assertEqual(parsed.fault, "sse-server-error")
        self.assertEqual(parsed.mode, "plan")
        self.assertEqual(parsed.permissions, "workspace")
        self.assertTrue(parsed.global_agents)
        self.assertEqual(parsed.lsp, ("pyright", "typescript"))
        self.assertEqual(parsed.modalities, "image")
        self.assertEqual(parsed.webfetch, "local")
        self.assertEqual(parsed.disable_tools, ("bash", "write"))
        self.assertIn("context=72000", parsed.as_text())
        self.assertIn("lsp=pyright,typescript", parsed.as_text())
        self.assertIn("modalities=image", parsed.as_text())
        self.assertIn("webfetch=local", parsed.as_text())
        self.assertIn("disable-tools=bash,write", parsed.as_text())
        self.assertEqual(parsed.payload()["modalities"], "image")
        self.assertEqual(parsed.payload()["disable_tools"], ["bash", "write"])
        self.assertEqual(parsed.payload()["mode"], "plan")

    def test_disable_tools_combines_with_mode_and_rejects_unknown_names(self):
        parsed = parse_options("mode=build;disable-tools=bash, write")
        self.assertEqual(parsed.mode, "build")
        self.assertEqual(parsed.disable_tools, ("bash", "write"))
        self.assertEqual(parsed.as_text(), "mode=build disable-tools=bash,write")
        for text in (
            "disable-tools=read",
            "disable-tools=bash,bash",
            "disable-tools=",
            "disable-tools=bash,",
            "disable-tools=bash,write;disable-tools=edit",
        ):
            with self.subTest(text=text):
                with self.assertRaises(FixtureError):
                    parse_options(text)

    def test_unknown_duplicate_and_empty_values_are_errors(self):
        for text in (
            "nope=1",
            "context=72000; context=1",
            "fault=",
            "context=0",
            "context=abc",
            "fault=http-500",
            "permissions=all",
            "global-agents=0",
            "lsp=",
            "lsp=vue",
            "modalities=pdf",
            "webfetch=httpbin",
            "disable-tools=read",
            "bare",
        ):
            with self.subTest(text=text):
                with self.assertRaises(FixtureError):
                    parse_options(text)


class CompactionTests(unittest.TestCase):
    def test_usable_window_matches_the_overflow_formula(self):
        # output limit 128000 is capped at OUTPUT_TOKEN_MAX (32000).
        self.assertEqual(compaction_usable(72000, 128000), 40000)
        self.assertEqual(compaction_usable(1_000_000, 128000), 968000)
        self.assertFalse(compaction_overflow(72000, 128000, 40000))
        self.assertTrue(compaction_overflow(72000, 128000, 40001))
        self.assertFalse(compaction_overflow(1_000_000, 128000, 71000))
        self.assertFalse(compaction_overflow(0, 128000, 10**9))

    def test_apply_context_limit_copies_and_overrides_every_model(self):
        original = anthropic_proxy_config("http://127.0.0.1:9", include_endpoint=True)
        updated = apply_context_limit(original, 72000)
        self.assertEqual(
            original["provider"]["anthropic"]["models"]["claude-opus-5-5"]["limit"]["context"],
            1_000_000,
        )
        limit = updated["provider"]["anthropic"]["models"]["claude-opus-5-5"]["limit"]
        self.assertEqual(limit["context"], 72000)
        self.assertEqual(limit["output"], 128000)
        self.assertEqual(updated["provider"]["anthropic"]["api"], "http://127.0.0.1:9")

    def test_empty_config_gets_the_proxy_model(self):
        updated = apply_context_limit({}, 72000)
        limit = updated["provider"]["anthropic"]["models"]["claude-opus-5-5"]["limit"]
        self.assertEqual(limit, {"context": 72000, "output": 128000})

    def test_config_without_a_model_entry_is_an_error(self):
        with self.assertRaises(FixtureError):
            apply_context_limit({"provider": {"anthropic": {"npm": "x"}}}, 72000)

    def test_fill_overrides_the_cell_config_only(self):
        prepared_config = anthropic_proxy_config("http://127.0.0.1:9", include_endpoint=False)
        prepared = {
            "binary": "/bin/true",
            "config": prepared_config,
            "permission_config": False,
            "harness": "opencode",
            "proxy": {},
        }
        spec = {
            "pr": "4838",
            "side": "with",
            "task": "taskflow",
            "trial": 1,
            "fixtures": {"context": 72000, "fault": None, "lsp": []},
        }
        out = Path(tempfile.mkdtemp())
        filled = _fill(spec, prepared, out, "tasks", "adapters", "claude-opus-5-5", 60)
        cell_limit = filled["config"]["provider"]["anthropic"]["models"]["claude-opus-5-5"]["limit"]
        self.assertEqual(cell_limit["context"], 72000)
        self.assertEqual(
            prepared_config["provider"]["anthropic"]["models"]["claude-opus-5-5"]["limit"]["context"],
            1_000_000,
        )

    def test_image_modalities_copy_the_model_and_keep_the_limit(self):
        original = anthropic_proxy_config("http://127.0.0.1:9", include_endpoint=True)
        updated = apply_image_modalities(original)
        model = original["provider"]["anthropic"]["models"]["claude-opus-5-5"]
        self.assertNotIn("modalities", model)
        copied = updated["provider"]["anthropic"]["models"]["claude-opus-5-5"]
        self.assertEqual(copied["modalities"], IMAGE_MODALITIES)
        self.assertEqual(copied["limit"]["context"], 1_000_000)
        self.assertEqual(copied["limit"]["output"], 128000)
        self.assertEqual(updated["provider"]["anthropic"]["api"], "http://127.0.0.1:9")
        self.assertIn("image", copied["modalities"]["input"])
        self.assertEqual(copied["modalities"]["output"], ["text"])

    def test_empty_config_gets_an_image_capable_proxy_model(self):
        updated = apply_image_modalities({})
        model = updated["provider"]["anthropic"]["models"]["claude-opus-5-5"]
        self.assertEqual(model["modalities"], IMAGE_MODALITIES)
        self.assertEqual(model["limit"]["output"], 128000)

    def test_fill_applies_modalities_without_touching_the_prepared_config(self):
        prepared_config = anthropic_proxy_config("http://127.0.0.1:9", include_endpoint=False)
        prepared = {
            "binary": "/bin/true",
            "config": prepared_config,
            "permission_config": False,
            "harness": "opencode",
            "proxy": {},
        }
        spec = {
            "pr": "3052",
            "side": "with",
            "task": "trig-image-read",
            "trial": 1,
            "fixtures": {"context": None, "modalities": "image", "lsp": []},
        }
        out = Path(tempfile.mkdtemp())
        filled = _fill(spec, prepared, out, "tasks", "adapters", "claude-opus-5-5", 60)
        cell = filled["config"]["provider"]["anthropic"]["models"]["claude-opus-5-5"]
        self.assertEqual(cell["modalities"]["input"], ["text", "image"])
        self.assertNotIn(
            "modalities",
            prepared_config["provider"]["anthropic"]["models"]["claude-opus-5-5"],
        )


def _png_facts(png: bytes) -> tuple[int, int, list[bytes], tuple[int, int, int]]:
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    pos = 8
    tags = []
    width = height = None
    payload = b""
    while pos + 8 <= len(png):
        length = struct.unpack(">I", png[pos:pos + 4])[0]
        tag = png[pos + 4:pos + 8]
        data = png[pos + 8:pos + 8 + length]
        tags.append(tag)
        if tag == b"IHDR":
            width, height = struct.unpack(">II", data[:8])
        if tag == b"IDAT":
            payload += data
        pos += 12 + length
    raw = zlib.decompress(payload)
    assert raw[0] == 0
    return width, height, tags, (raw[1], raw[2], raw[3])


class LocalImageTests(unittest.TestCase):
    def test_named_colours_are_far_apart(self):
        import math
        colours = dict(NAMED_COLOURS)
        self.assertEqual(
            list(colours),
            ["red", "orange", "yellow", "green", "cyan", "blue", "purple", "pink", "brown", "grey"],
        )
        names = list(colours)
        worst = min(
            math.dist(colours[a], colours[b])
            for i, a in enumerate(names)
            for b in names[i + 1:]
        )
        self.assertGreater(worst, 100)

    def test_seed_picks_a_stable_named_colour(self):
        name, rgb = colour_for_seed(3)
        self.assertEqual(name, NAMED_COLOURS[3][0])
        self.assertEqual(rgb, NAMED_COLOURS[3][1])
        self.assertEqual(colour_for_seed(3), colour_for_seed(3 + len(NAMED_COLOURS)))

    def test_png_is_a_metadata_free_square(self):
        png = png_for_colour("cyan")
        width, height, tags, pixel = _png_facts(png)
        self.assertEqual((width, height), (PNG_SIDE, PNG_SIDE))
        self.assertEqual(pixel, dict(NAMED_COLOURS)["cyan"])
        self.assertEqual(set(tags), {b"IHDR", b"IDAT", b"IEND"})

    def test_local_png_is_a_named_colour_and_served_as_an_image(self):
        env = {}
        server = bind_local_webfetch(env, {"webfetch": "local"})
        self.addCleanup(server.close)
        self.assertEqual(WEBFETCH_PLACEHOLDER, "__OBENCH_WEBFETCH_URL__")
        url = env["OBENCH_OPENCODE_WEBFETCH_URL"]
        self.assertTrue(url.startswith("http://127.0.0.1:"))
        self.assertTrue(url.endswith("/color.png"))
        self.assertEqual(env["OBENCH_WEBFETCH_COLOUR"], server.colour)
        self.assertEqual(env["OBENCH_WEBFETCH_SEED"], str(server.seed))
        self.assertIn(server.colour, dict(NAMED_COLOURS))
        with urllib.request.urlopen(url, timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertTrue(response.headers["Content-Type"].startswith("image/png"))
            body = response.read()
        width, height, tags, pixel = _png_facts(body)
        self.assertEqual((width, height), (PNG_SIDE, PNG_SIDE))
        self.assertEqual(pixel, dict(NAMED_COLOURS)[server.colour])
        self.assertEqual(set(tags), {b"IHDR", b"IDAT", b"IEND"})
        self.assertIsNone(bind_local_webfetch(env, {}))
        self.assertNotIn("OBENCH_OPENCODE_WEBFETCH_URL", env)
        self.assertNotIn("OBENCH_WEBFETCH_COLOUR", env)


class _Upstream(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        self.server.seen.append(self.path)
        payload = b'{"id":"msg","usage":{"input_tokens":1,"output_tokens":1}}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
        del body

    def log_message(self, fmt, *args):
        return


def _post(url, body):
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


class _UsageUpstream(BaseHTTPRequestHandler):
    """Main-session and subagent responses, chosen from the forwarded prompt."""

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        if b"subagent" in body:
            usage = {
                "input_tokens": 50,
                "output_tokens": 20,
                "cache_read_input_tokens": 3,
                "cache_creation_input_tokens": 1,
            }
        else:
            usage = {
                "input_tokens": 100,
                "output_tokens": 40,
                "cache_read_input_tokens": 10,
                "cache_creation_input_tokens": 5,
            }
        payload = json.dumps({"id": "msg", "usage": usage}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        return


class FaultInjectionTests(unittest.TestCase):
    def setUp(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Upstream)
        self.httpd.seen = []
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.httpd.server_address
        self.proxy = start_proxy("proj", token="tok", upstream=f"http://{host}:{port}")
        self.addCleanup(self.proxy.close)
        self.addCleanup(self.httpd.shutdown)
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(lambda: self.thread.join(timeout=2))
        self.body = json.dumps({
            "model": "claude-opus-5-5",
            "max_tokens": 8,
            "messages": [],
            "tools": [{"name": "bash", "input_schema": {"type": "object"}}],
        }).encode()

    def test_first_messages_post_is_the_fault_and_later_posts_forward(self):
        self.proxy.arm_fault("cell-1", "http-529")
        status, _headers, payload = _post(
            self.proxy.base_url + "/c/cell-1/v1/messages/count_tokens", self.body,
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(self.httpd.seen), 1)
        status, _headers, payload = _post(
            self.proxy.base_url + "/c/cell-1/v1/messages", self.body,
        )
        self.assertEqual(status, 529)
        self.assertIn(b"overloaded_error", payload)
        self.assertEqual(len(self.httpd.seen), 1)
        status, _headers, payload = _post(
            self.proxy.base_url + "/c/cell-1/v1/messages", self.body,
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(self.httpd.seen), 2)

        self.proxy.arm_fault("cell-1", "http-429")
        status, headers, payload = _post(
            self.proxy.base_url + "/c/cell-1/v1/messages", self.body,
        )
        self.assertEqual(status, 429)
        self.assertEqual(headers.get("Retry-After"), "1")
        self.assertIn(b"rate_limit_error", payload)
        self.assertEqual(len(self.httpd.seen), 2)

        self.proxy.arm_fault("cell-2", "sse-server-error")
        status, headers, payload = _post(
            self.proxy.base_url + "/c/cell-2/v1/messages", self.body,
        )
        self.assertEqual(status, 200)
        self.assertIn("text/event-stream", headers.get("Content-Type", ""))
        self.assertIn(b"message_start", payload)
        self.assertIn(
            b'{"type":"error","error":{"type":"server_error","message":"no_kv_space"}}',
            payload,
        )
        self.assertEqual(len(self.httpd.seen), 2)

    def test_unknown_fault_is_rejected(self):
        with self.assertRaises(ProxyError):
            self.proxy.arm_fault("cell-1", "http-500")

    def test_title_and_tiny_requests_do_not_consume_the_fault(self):
        self.proxy.arm_fault("cell-1", "http-529", 1)
        title = json.dumps({
            "model": "claude-opus-5-5",
            "max_tokens": 20,
            "system": "You are a title generator. Never use tools.",
            "messages": [{"role": "user", "content": "hello"}],
        }).encode()
        status, _headers, _payload = _post(
            self.proxy.base_url + "/c/cell-1/v1/messages", title,
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(self.httpd.seen), 1)
        tiny = b'{"model":"claude-opus-5-5","max_tokens":8,"messages":[]}'
        status, _headers, _payload = _post(
            self.proxy.base_url + "/c/cell-1/v1/messages", tiny,
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(self.httpd.seen), 2)
        status, _headers, payload = _post(
            self.proxy.base_url + "/c/cell-1/v1/messages", self.body,
        )
        self.assertEqual(status, 529)
        self.assertIn(b"overloaded_error", payload)
        self.assertEqual(len(self.httpd.seen), 2)

    def test_fault_count_covers_that_many_main_loop_requests(self):
        self.proxy.arm_fault("cell-1", "http-529", 3)
        for _ in range(3):
            status, _headers, payload = _post(
                self.proxy.base_url + "/c/cell-1/v1/messages", self.body,
            )
            self.assertEqual(status, 529)
            self.assertIn(b"overloaded_error", payload)
        self.assertEqual(len(self.httpd.seen), 0)
        status, _headers, _payload = _post(
            self.proxy.base_url + "/c/cell-1/v1/messages", self.body,
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(self.httpd.seen), 1)


class SubagentMeterTests(unittest.TestCase):
    def test_subagent_request_is_included_in_the_cell_total(self):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _UsageUpstream)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        host, port = httpd.server_address
        ledger = Path(tempfile.mkdtemp())
        proxy = start_proxy(
            "proj", token="tok", upstream=f"http://{host}:{port}", ledger_dir=ledger,
        )
        self.addCleanup(proxy.close)
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        self.addCleanup(lambda: thread.join(timeout=2))
        main_body = json.dumps({
            "model": "claude-opus-5-5",
            "messages": [{"role": "user", "content": "main"}],
        }).encode()
        child_body = json.dumps({
            "model": "claude-opus-5-5",
            "messages": [{"role": "user", "content": "subagent"}],
        }).encode()
        for url, body in (
            (proxy.base_url + "/c/cell-main/v1/messages", main_body),
            (proxy.base_url + "/c/cell-main/v1/messages", child_body),
            (proxy.base_url + "/c/cell-other/v1/messages", main_body),
        ):
            status, _headers, _payload = _post(url, body)
            self.assertEqual(status, 200)
        self.assertEqual(len((ledger / "cell-main.jsonl").read_text().splitlines()), 2)
        self.assertEqual(len((ledger / "cell-other.jsonl").read_text().splitlines()), 1)
        row = {
            "tokens_input_uncached": 100,
            "tokens_output": 40,
            "tokens_cache_read": 10,
            "tokens_cache_write": 5,
            "token_basis": "vendor_split",
            "usage_raw": [{"input": 100, "output": 40}],
        }
        apply_cell_meter(row, {"ledger_dir": str(ledger), "cell_id": "cell-main"})
        self.assertEqual(row["requests_count"], 2)
        self.assertEqual(row["requests_input_uncached"], 150)
        self.assertEqual(row["requests_output"], 60)
        self.assertEqual(row["requests_cache_read"], 13)
        self.assertEqual(row["requests_cache_write"], 6)
        self.assertEqual(row["tokens_input_uncached"], 150)
        self.assertEqual(row["tokens_output"], 60)
        self.assertEqual(row["tokens_cache_read"], 13)
        self.assertEqual(row["tokens_cache_write"], 6)
        self.assertEqual(row["tokens_main_input_uncached"], 100)
        self.assertEqual(row["tokens_main_output"], 40)
        self.assertEqual(row["tokens_main_cache_read"], 10)
        self.assertEqual(row["tokens_main_cache_write"], 5)
        self.assertEqual(row["tokens_main_calls"], 1)
        self.assertEqual(row["token_basis_main"], "vendor_split")
        self.assertEqual(row["usage_raw"], [{"input": 100, "output": 40}])
        self.assertAlmostEqual(row["requests_cost_usd"], 0.0018326)
        self.assertAlmostEqual(row["requests_cost_usd"], row_cost(row))
        other = {
            "tokens_input_uncached": 100,
            "tokens_output": 40,
            "tokens_cache_read": 10,
            "tokens_cache_write": 5,
            "token_basis": "vendor_split",
            "usage_raw": [{"input": 100}],
        }
        apply_cell_meter(other, {"ledger_dir": str(ledger), "cell_id": "cell-other"})
        self.assertEqual(other["requests_count"], 1)
        self.assertEqual(other["requests_input_uncached"], 100)
        self.assertEqual(other["tokens_main_calls"], 1)


class _ToolAndUsage(BaseHTTPRequestHandler):
    """A messages response that carries both a tool call and token usage."""

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if b"tool-only" in raw:
            body = {
                "content": [{
                    "type": "tool_use",
                    "id": "toolu_9",
                    "name": "bash",
                    "input": {"command": "pwd"},
                }],
            }
        else:
            body = {
                "id": "msg",
                "content": [{
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "bash",
                    "input": {"command": "ls /tmp"},
                }],
                "usage": {
                    "input_tokens": 7,
                    "output_tokens": 9,
                    "cache_read_input_tokens": 1,
                    "cache_creation_input_tokens": 0,
                    "duration_ms": 15,
                },
            }
        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        return


class LedgerTrimTests(unittest.TestCase):
    def test_ledger_rows_keep_usage_and_timing_and_the_same_count(self):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _ToolAndUsage)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        host, port = httpd.server_address
        ledger = Path(tempfile.mkdtemp())
        proxy = start_proxy(
            "proj", token="tok", upstream=f"http://{host}:{port}", ledger_dir=ledger,
        )
        self.addCleanup(proxy.close)
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        self.addCleanup(lambda: thread.join(timeout=2))
        body = json.dumps({
            "model": "claude-opus-5-5",
            "max_tokens": 64,
            "tools": [{"name": "bash"}],
            "messages": [{"role": "user", "content": "main"}],
        }).encode()
        tool_only = json.dumps({
            "model": "claude-opus-5-5",
            "max_tokens": 64,
            "messages": [{"role": "user", "content": "tool-only"}],
        }).encode()
        for url, payload in (
            (proxy.base_url + "/c/cell-trim/v1/messages", body),
            (proxy.base_url + "/c/cell-trim/v1/messages", body),
            (proxy.base_url + "/c/cell-tool/v1/messages", tool_only),
        ):
            status, _headers, _response = _post(url, payload)
            self.assertEqual(status, 200)
        mixed = (ledger / "cell-trim.jsonl").read_text(encoding="utf-8").splitlines()
        only = (ledger / "cell-tool.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(mixed), 2)
        self.assertEqual(len(only), 1)
        row = json.loads(mixed[0])
        self.assertEqual(row["usage"]["input_tokens"], 7)
        self.assertEqual(row["usage"]["output_tokens"], 9)
        self.assertEqual(row["duration_ms"], 15)
        self.assertNotIn("name", row["usage"])
        self.assertNotIn("input", row["usage"])
        self.assertNotIn("bash", mixed[0])
        self.assertNotIn("toolu_1", mixed[0])
        tool_row = json.loads(only[0])
        self.assertEqual(tool_row["usage"], {})
        self.assertNotIn("toolu_9", only[0])
        self.assertNotIn("bash", only[0])


class _SlowStream(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        def chunk(payload: bytes) -> None:
            self.wfile.write(f"{len(payload):X}\r\n".encode("ascii"))
            self.wfile.write(payload)
            self.wfile.write(b"\r\n")
            self.wfile.flush()

        chunk(b"data: {\"type\":\"ping\"}\n\n")
        time.sleep(0.45)
        chunk(b"data: {\"type\":\"message_stop\"}\n\n")
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()

    def log_message(self, fmt, *args):
        return


class ProxyByteTests(unittest.TestCase):
    def test_stream_bytes_grow_before_the_response_finishes(self):
        upstream = ThreadingHTTPServer(("127.0.0.1", 0), _SlowStream)
        thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        thread.start()
        host, port = upstream.server_address
        ledger = Path(tempfile.mkdtemp())
        proxy = start_proxy(
            "proj", token="tok", upstream=f"http://{host}:{port}", ledger_dir=ledger,
        )
        self.addCleanup(proxy.close)
        self.addCleanup(upstream.shutdown)
        self.addCleanup(upstream.server_close)
        self.addCleanup(lambda: thread.join(timeout=2))
        path = cell_bytes_path(ledger, "cell-9")
        body = b'{"stream":true,"messages":[]}'

        def client():
            _post(proxy.base_url + "/c/cell-9/v1/messages", body)

        worker = threading.Thread(target=client)
        worker.start()
        self.addCleanup(lambda: worker.join(timeout=3))
        deadline = time.time() + 3
        seen = []
        while time.time() < deadline:
            if path.is_file():
                try:
                    seen.append(int(path.read_text(encoding="utf-8")))
                except ValueError:
                    pass
                if len(set(seen)) >= 2:
                    break
            time.sleep(0.05)
        worker.join(timeout=3)
        self.assertGreaterEqual(len(set(seen)), 2)
        self.assertGreater(max(seen), min(seen))

    def test_unscoped_post_is_not_attributed(self):
        upstream = ThreadingHTTPServer(("127.0.0.1", 0), _Upstream)
        upstream.seen = []
        thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        thread.start()
        host, port = upstream.server_address
        ledger = Path(tempfile.mkdtemp())
        proxy = start_proxy(
            "proj", token="tok", upstream=f"http://{host}:{port}", ledger_dir=ledger,
        )
        self.addCleanup(proxy.close)
        self.addCleanup(upstream.shutdown)
        self.addCleanup(upstream.server_close)
        self.addCleanup(lambda: thread.join(timeout=2))
        status, _headers, _payload = _post(
            proxy.base_url + "/v1/messages",
            b'{"messages":[]}',
        )
        self.assertEqual(status, 200)
        self.assertEqual(list(ledger.glob("*.bytes")), [])
        self.assertEqual(list(ledger.glob("*.jsonl")), [])


if __name__ == "__main__":
    unittest.main()
