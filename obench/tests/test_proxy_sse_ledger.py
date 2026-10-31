"""Per-request SSE record on the proxy ledger, and the raw SSE dump."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from obench.tests.test_vertex_proxy_harness_api import STREAM, _Vertex, _event, _post
from thesis.ab.vertex_anthropic_proxy import (
    SseObserver,
    sse_dump_cap,
    sse_dump_dir,
    start_proxy,
    stream_summary,
)

BODY = {
    "model": "claude-opus-5-5", "max_tokens": 64, "stream": True,
    "messages": [{"role": "user", "content": "hi"}],
}

REFUSAL = b"".join([
    _event("message_start", {"type": "message_start", "message": {
        "id": "m", "type": "message", "role": "assistant", "content": [],
        "usage": {"input_tokens": 5, "output_tokens": 0}}}),
    _event("message_delta", {"type": "message_delta", "delta": {"stop_reason": "refusal"},
                             "usage": {"output_tokens": 0}}),
    _event("message_stop", {"type": "message_stop"}),
])

ERRORED = b"".join([
    _event("message_start", {"type": "message_start", "message": {
        "id": "m", "type": "message", "role": "assistant", "content": [],
        "usage": {"input_tokens": 5, "output_tokens": 0}}}),
    _event("error", {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}),
])


class ObserverTests(unittest.TestCase):
    def test_counts_stop_reason_and_stop_across_split_chunks(self):
        obs = SseObserver()
        for i in range(0, len(STREAM), 7):
            obs.feed(STREAM[i:i + 7])
        info = obs.finish()
        self.assertTrue(info["message_stop"])
        self.assertFalse(info["closed_before_stop"])
        self.assertEqual(info["stop_reason"], "tool_use")
        self.assertEqual(info["sse_event_counts"]["message_stop"], 1)
        self.assertEqual(info["sse_event_counts"]["content_block_delta"],
                         STREAM.count(b"event: content_block_delta"))
        self.assertEqual(info["response_bytes"], len(STREAM))
        self.assertEqual(info["sse_errors"], [])

    def test_error_event_and_cut_stream(self):
        obs = SseObserver()
        obs.feed(ERRORED)
        info = obs.finish()
        self.assertFalse(info["message_stop"])
        self.assertTrue(info["closed_before_stop"])
        self.assertEqual(info["sse_errors"], [{"type": "overloaded_error", "message": "Overloaded"}])

    def test_dump_cap_defaults(self):
        self.assertEqual(sse_dump_cap({}), 0)
        self.assertEqual(sse_dump_cap({"OBENCH_GATE_CELL": "1"}), 4 * 1024 * 1024)
        self.assertEqual(sse_dump_cap({"OBENCH_GATE_CELL": "1", "OBENCH_PROXY_SSE_DUMP_BYTES": "0"}), 0)
        self.assertEqual(sse_dump_cap({"OBENCH_PROXY_SSE_DUMP_BYTES": "100"}), 100)
        self.assertEqual(sse_dump_cap({"OBENCH_PROXY_SSE_DUMP_BYTES": "x"}), 0)

    def test_stream_summary_for_cell_row(self):
        rows = [{"stream": {"stop_reason": "tool_use", "closed_before_stop": False, "response_bytes": 10}},
                {"stream": {"stop_reason": None, "closed_before_stop": True, "response_bytes": 5,
                            "sse_errors": [{"type": "e", "message": "m"}]}},
                {"usage": {}}]
        out = stream_summary(rows)
        self.assertEqual(out["proxy_stream_calls"], 2)
        self.assertEqual(out["proxy_stream_closed_before_stop"], 1)
        self.assertEqual(out["proxy_stop_reasons"], ["tool_use", None])
        self.assertEqual(out["proxy_response_bytes"], 15)
        self.assertEqual(out["proxy_sse_errors"], [{"type": "e", "message": "m"}])


class ProxyLedgerTests(unittest.TestCase):
    def start(self, env):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Vertex)
        httpd.seen, httpd.queue = [], []
        httpd.json_body, httpd.stream_body = b"{}", STREAM
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: thread.join(timeout=2))
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        ledger = Path(tempfile.mkdtemp())
        patcher = patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        for key in ("OBENCH_GATE_CELL", "OBENCH_PROXY_SSE_DUMP_BYTES"):
            if key not in env:
                os.environ.pop(key, None)
        host, port = httpd.server_address
        proxy = start_proxy("proj", token="tok", upstream=f"http://{host}:{port}",
                            ledger_dir=ledger, route_by_request=True)
        self.addCleanup(proxy.close)
        return httpd, proxy, ledger

    def rows(self, ledger, cell):
        return [json.loads(l) for l in (ledger / f"{cell}.jsonl").read_text().splitlines()]

    def test_ledger_row_carries_stream_record_and_no_dump_by_default(self):
        _httpd, proxy, ledger = self.start({})
        status, _ = _post(proxy.base_url + "/c/c1/v1/messages", BODY)
        self.assertEqual(status, 200)
        stream = self.rows(ledger, "c1")[0]["stream"]
        self.assertEqual(stream["stop_reason"], "tool_use")
        self.assertTrue(stream["message_stop"])
        self.assertEqual(stream["response_bytes"], len(STREAM))
        self.assertNotIn("sse_dump", stream)
        self.assertFalse(sse_dump_dir(ledger, "c1").exists())

    def test_gate_cell_dumps_raw_sse_and_records_refusal(self):
        httpd, proxy, ledger = self.start({"OBENCH_GATE_CELL": "1"})
        httpd.queue.append((REFUSAL, True))
        _post(proxy.base_url + "/c/g1/v1/messages", BODY)
        stream = self.rows(ledger, "g1")[0]["stream"]
        self.assertEqual(stream["stop_reason"], "refusal")
        self.assertEqual(stream["sse_dump"], "0001.sse")
        self.assertEqual((sse_dump_dir(ledger, "g1") / "0001.sse").read_bytes(), REFUSAL)

    def test_dump_is_capped_and_cut_stream_is_flagged(self):
        httpd, proxy, ledger = self.start({"OBENCH_PROXY_SSE_DUMP_BYTES": "40"})
        httpd.queue.append((ERRORED, True))
        _post(proxy.base_url + "/c/e1/v1/messages", BODY)
        stream = self.rows(ledger, "e1")[0]["stream"]
        self.assertTrue(stream["closed_before_stop"])
        self.assertEqual(stream["sse_errors"][0]["type"], "overloaded_error")
        dumped = (sse_dump_dir(ledger, "e1") / "0001.sse").read_bytes()
        self.assertTrue(dumped.startswith(ERRORED[:40]))
        self.assertIn(b"# truncated:", dumped)


if __name__ == "__main__":
    unittest.main()
