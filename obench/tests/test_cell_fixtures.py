"""Per-PR fixture options, context-limit override, and proxy fault injection."""

from __future__ import annotations

import json
import struct
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from thesis.ab.cell_fixtures import (
    IMAGE_MODALITIES,
    WEBFETCH_PLACEHOLDER,
    FixtureError,
    apply_context_limit,
    apply_image_modalities,
    bind_local_webfetch,
    compaction_overflow,
    compaction_usable,
    parse_options,
)
from thesis.ab.compat import anthropic_proxy_config
from thesis.ab.run_ab import _fill
from thesis.ab.vertex_anthropic_proxy import ProxyError, start_proxy


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
            "modalities=image; webfetch=local"
        )
        self.assertEqual(parsed.context, 72000)
        self.assertEqual(parsed.fault, "sse-server-error")
        self.assertEqual(parsed.mode, "plan")
        self.assertEqual(parsed.permissions, "workspace")
        self.assertTrue(parsed.global_agents)
        self.assertEqual(parsed.lsp, ("pyright", "typescript"))
        self.assertEqual(parsed.modalities, "image")
        self.assertEqual(parsed.webfetch, "local")
        self.assertIn("context=72000", parsed.as_text())
        self.assertIn("lsp=pyright,typescript", parsed.as_text())
        self.assertIn("modalities=image", parsed.as_text())
        self.assertIn("webfetch=local", parsed.as_text())
        self.assertEqual(parsed.payload()["modalities"], "image")

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


def _png_pixel(png: bytes) -> tuple[int, int, int]:
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    pos = 8
    payload = b""
    while pos + 8 <= len(png):
        length = struct.unpack(">I", png[pos:pos + 4])[0]
        tag = png[pos + 4:pos + 8]
        data = png[pos + 8:pos + 8 + length]
        if tag == b"IDAT":
            payload += data
        pos += 12 + length
    raw = zlib.decompress(payload)
    assert raw[0] == 0
    return raw[1], raw[2], raw[3]


class LocalImageTests(unittest.TestCase):
    def test_local_png_is_red_and_served_as_an_image(self):
        env = {}
        server = bind_local_webfetch(env, {"webfetch": "local"})
        self.addCleanup(server.close)
        self.assertEqual(WEBFETCH_PLACEHOLDER, "__OBENCH_WEBFETCH_URL__")
        url = env["OBENCH_OPENCODE_WEBFETCH_URL"]
        self.assertTrue(url.startswith("http://127.0.0.1:"))
        self.assertTrue(url.endswith("/color.png"))
        with urllib.request.urlopen(url, timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertTrue(response.headers["Content-Type"].startswith("image/png"))
            body = response.read()
        self.assertEqual(_png_pixel(body), (255, 0, 0))
        self.assertIsNone(bind_local_webfetch(env, {}))
        self.assertNotIn("OBENCH_OPENCODE_WEBFETCH_URL", env)


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
        self.body = b'{"model":"claude-opus-5-5","max_tokens":8,"messages":[]}'

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


if __name__ == "__main__":
    unittest.main()
