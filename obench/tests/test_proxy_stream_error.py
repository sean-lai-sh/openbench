"""P1: the upstream SSE stream breaks mid-response.

The proxy must record the break on the ledger (error type, partial-usage
flag) and end the client stream with an SSE error event and a proper chunked
terminator, instead of hanging, dropping the record, or calling it a client
disconnect.
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from obench.tests.test_vertex_proxy_harness_api import _event
from thesis.ab.vertex_anthropic_proxy import read_no_usage_records, start_proxy

BODY = {
    "model": "claude-opus-5-5", "max_tokens": 64, "stream": True,
    "messages": [{"role": "user", "content": "hi"}],
}

PARTIAL = b"".join([
    _event("message_start", {"type": "message_start", "message": {
        "id": "m", "type": "message", "role": "assistant", "content": [],
        "usage": {"input_tokens": 7, "output_tokens": 0}}}),
    _event("content_block_start", {"type": "content_block_start", "index": 0,
                                   "content_block": {"type": "text", "text": ""}}),
])


class _Breaks(BaseHTTPRequestHandler):
    """Sends one chunk of SSE, then drops the socket mid-chunked-body."""

    protocol_version = "HTTP/1.1"

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        payload = self.server.payload
        self.wfile.write(f"{len(payload):X}\r\n".encode() + payload + b"\r\n")
        # Promise more bytes than we send, then cut the connection.
        self.wfile.write(b"400\r\npartial")
        self.wfile.flush()
        self.connection.shutdown(socket.SHUT_RDWR)
        self.close_connection = True

    def log_message(self, *_args):
        return


class UpstreamStreamErrorTests(unittest.TestCase):
    def start(self, payload: bytes):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Breaks)
        httpd.payload = payload
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: thread.join(timeout=2))
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        patcher = patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        for key in ("OBENCH_GATE_CELL", "OBENCH_PROXY_SSE_DUMP_BYTES"):
            os.environ.pop(key, None)
        ledger = Path(tempfile.mkdtemp())
        host, port = httpd.server_address
        proxy = start_proxy("proj", token="tok", upstream=f"http://{host}:{port}",
                            ledger_dir=ledger, route_by_request=True)
        self.addCleanup(proxy.close)
        return proxy, ledger

    def post(self, url):
        request = urllib.request.Request(
            url, data=json.dumps(BODY).encode(), method="POST",
            headers={"Content-Type": "application/json"},
        )
        # A full read only returns if the proxy wrote the chunked terminator.
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read()

    def test_client_gets_partial_bytes_then_error_event_and_clean_close(self):
        proxy, _ledger = self.start(PARTIAL)
        status, body = self.post(proxy.base_url + "/c/s1/v1/messages")
        self.assertEqual(status, 200)
        self.assertTrue(body.startswith(PARTIAL))
        tail = body[len(PARTIAL):]
        self.assertIn(b"event: error\n", tail)
        data = json.loads(tail.split(b"data: ", 1)[1].split(b"\n", 1)[0])
        self.assertEqual(data["type"], "error")
        self.assertEqual(data["error"]["type"], "api_error")
        self.assertIn("upstream stream error", data["error"]["message"])

    def test_ledger_records_error_type_and_partial_usage(self):
        proxy, ledger = self.start(PARTIAL)
        self.post(proxy.base_url + "/c/s2/v1/messages")
        rows = [json.loads(l) for l in (ledger / "s2.jsonl").read_text().splitlines()]
        self.assertEqual(len(rows), 1)
        stream = rows[0]["stream"]
        self.assertEqual(stream["upstream_error"]["type"], "IncompleteRead")
        self.assertTrue(stream["partial_usage"])
        self.assertFalse(stream["client_disconnected"])
        self.assertTrue(stream["closed_before_stop"])

    def test_break_before_any_usage_flags_no_partial_usage(self):
        proxy, ledger = self.start(b": ping\n\n")
        status, body = self.post(proxy.base_url + "/c/s3/v1/messages")
        self.assertEqual(status, 200)
        self.assertIn(b"event: error\n", body)
        # No usage arrived, so the row goes to the no-usage sibling file.
        self.assertFalse((ledger / "s3.jsonl").exists())
        rows = read_no_usage_records(ledger, "s3")
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["stream"]["partial_usage"])
        self.assertIn("upstream_error", rows[0]["stream"])


if __name__ == "__main__":
    unittest.main()
