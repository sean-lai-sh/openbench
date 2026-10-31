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
from thesis.ab.run_ab import PROXY_TRACE_FIELDS, apply_cell_meter
from thesis.ab.vertex_anthropic_proxy import (
    LOCATION,
    MODEL_ID,
    SseObserver,
    _append_ledger,
    cell_no_usage_path,
    read_no_usage_records,
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


NO_USAGE = _event("error", {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}})


class NoUsageCountTests(unittest.TestCase):
    """Streams with no usage must not move the fields the analysis already uses."""

    FIELDS = ("proxy_requests", "untraced_requests", "requests_count", "trace_requests",
              "off_protocol", "model_match_reason", "proxy_cost_usd", "requests_error",
              "upstream_model", "requested_model", "endpoint_location", "route")

    def ledger(self):
        root = Path(tempfile.mkdtemp())
        for _ in range(2):
            _append_ledger(root, "c", {"input_tokens": 100, "output_tokens": 10},
                           status=200, upstream_model=MODEL_ID, requested_model=MODEL_ID,
                           endpoint_location=LOCATION, stream={"stop_reason": "end_turn"})
        return root

    def meter(self, root, require=True):
        row = {"turns": 2}
        return apply_cell_meter(row, {"ledger_dir": str(root), "cell_id": "c"},
                                protocol_model=MODEL_ID, protocol_location=LOCATION,
                                require_model_match=require)

    def add_no_usage(self, root, n, model="some-other-model"):
        for _ in range(n):
            # A wrong model and location: if these rows were counted, the
            # off_protocol and model-match checks would flip.
            _append_ledger(root, "c", None, status=200, upstream_model=model,
                           requested_model="x", endpoint_location="us-east5",
                           stream={"stop_reason": None, "closed_before_stop": True},
                           no_usage=True)

    def test_existing_count_fields_ignore_no_usage_streams(self):
        before = self.meter(self.ledger())
        root = self.ledger()
        self.add_no_usage(root, 3)
        after = self.meter(root)
        for key in self.FIELDS:
            self.assertEqual(after.get(key), before.get(key), key)
        self.assertEqual(after["proxy_requests"], 2)
        self.assertEqual(after["requests_count"], 2)
        self.assertEqual(after["untraced_requests"], 0)
        self.assertFalse(after["off_protocol"])
        self.assertIsNone(after["model_match_reason"])
        self.assertEqual(before["proxy_requests_no_usage"], 0)
        self.assertEqual(after["proxy_requests_no_usage"], 3)
        self.assertEqual(after["proxy_stream_calls"], 5)
        self.assertEqual(after["proxy_stream_closed_before_stop"], 3)
        self.assertIn("proxy_requests_no_usage", PROXY_TRACE_FIELDS)

    def test_no_usage_stream_costs_zero(self):
        root = Path(tempfile.mkdtemp())
        (root / "c.jsonl").write_text("")
        self.add_no_usage(root, 2, model=MODEL_ID)
        row = self.meter(root, require=False)
        self.assertEqual(row["proxy_cost_usd"], 0.0)
        self.assertEqual(row["requests_count"], 0)
        self.assertEqual(row["proxy_requests"], 0)
        self.assertEqual(row["proxy_requests_no_usage"], 2)

    def test_proxy_writes_no_usage_stream_to_sibling_file_only(self):
        httpd, proxy, ledger = ProxyLedgerTests.start(self, {})
        httpd.queue.append((NO_USAGE, True))
        status, body = _post(proxy.base_url + "/c/n1/v1/messages", BODY)
        self.assertEqual(body, NO_USAGE)
        main = ledger / "n1.jsonl"
        self.assertTrue(not main.exists() or main.read_text() == "")
        rows = read_no_usage_records(ledger, "n1")
        self.assertEqual(len(rows), 1)
        self.assertNotIn("usage", rows[0])
        self.assertTrue(rows[0]["stream"]["closed_before_stop"])
        self.assertEqual(cell_no_usage_path(ledger, "n1").name, "n1.no_usage.jsonl")


class ClientBytesTests(unittest.TestCase):
    def test_client_bytes_identical_with_observer_and_dump_on(self):
        for env in ({}, {"OBENCH_GATE_CELL": "1"}):
            for body in (STREAM, REFUSAL, ERRORED):
                httpd, proxy, _ledger = ProxyLedgerTests.start(self, env)
                httpd.queue.append((body, True))
                _status, got = _post(proxy.base_url + "/c/b1/v1/messages", BODY)
                self.assertEqual(got, body)


if __name__ == "__main__":
    unittest.main()
