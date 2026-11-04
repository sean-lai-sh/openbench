"""``POST /v1/responses`` on the Vertex proxy (the Codex hard-suite arm).

Vertex is the same local stub as test_vertex_proxy_harness_api. The key
property: a Responses request is metered from the upstream Anthropic usage
into the same ledger fields as a ``/v1/messages`` request (Pi) and a
``/v1/chat/completions`` request (OpenCode), so per-cell tokens and cost are
comparable across the three arms.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from obench.tests.test_vertex_proxy_harness_api import MESSAGE, STREAM, _post, _Vertex
from thesis.ab.responses_api import decode_reasoning, encode_reasoning
from thesis.ab.vertex_anthropic_proxy import (
    cache_miss_headers_path,
    read_call_totals,
    responses_capture_path,
    start_proxy,
)

FIXTURES = Path(__file__).resolve().parents[2] / "thesis" / "ab" / "fixtures" / "responses"
_METER_KEYS = ("input_uncached", "output", "cache_read", "cache_write", "usage", "upstream_model",
               "endpoint_location", "status")


def codex_request(stream: bool = False) -> dict:
    body = json.loads((FIXTURES / "codex-request.json").read_text(encoding="utf-8"))
    body["stream"] = stream
    return body


def responses_sse(payload: bytes) -> list:
    found = []
    for block in payload.decode("utf-8").split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data:"):
                found.append(json.loads(line[5:].strip()))
    return found


def ledger_rows(ledger: Path, cell: str) -> list:
    return [json.loads(line) for line in (ledger / f"{cell}.jsonl").read_text().splitlines() if line.strip()]


class _ErrorVertex(_Vertex):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        payload = b'{"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}'
        self.send_response(529)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class ResponsesEndpointTests(unittest.TestCase):
    handler = _Vertex

    def setUp(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self.handler)
        self.httpd.seen = []
        self.httpd.queue = []
        self.httpd.json_body = json.dumps(MESSAGE).encode("utf-8")
        self.httpd.stream_body = STREAM
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.ledger = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.ledger, True)
        host, port = self.httpd.server_address
        self.proxy = start_proxy("proj", token="tok", upstream=f"http://{host}:{port}",
                                 ledger_dir=self.ledger, route_by_request=True)
        self.addCleanup(self.proxy.close)
        self.addCleanup(self.httpd.shutdown)
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(lambda: self.thread.join(timeout=2))

    def url(self, cell: str, route: str) -> str:
        return f"{self.proxy.base_url}/c/{cell}/v1/{route}"


class ResponsesNonStream(ResponsesEndpointTests):
    def test_translates_request_reply_and_meters_usage(self):
        status, payload = _post(self.url("cell-r", "responses"), codex_request())
        self.assertEqual(status, 200)
        resp = json.loads(payload)
        self.assertEqual(resp["object"], "response")
        self.assertEqual(resp["status"], "completed")
        self.assertEqual(resp["model"], "claude-sonnet-5-5")
        self.assertEqual([i["type"] for i in resp["output"]], ["message", "function_call"])
        self.assertEqual(resp["output"][0]["content"][0]["text"], "running")
        self.assertEqual(resp["output"][1]["call_id"], "toolu_1")
        self.assertEqual(json.loads(resp["output"][1]["arguments"]), {"cmd": "ls"})
        self.assertEqual(resp["usage"]["input_tokens"], 17)  # 11 uncached + 4 read + 2 write
        self.assertEqual(resp["usage"]["input_tokens_details"]["cached_tokens"], 4)
        self.assertEqual(resp["usage"]["output_tokens"], 7)

        seen = self.httpd.seen[-1]
        self.assertTrue(seen["path"].endswith("/models/claude-sonnet-5-5:rawPredict"))
        forwarded = json.loads(seen["body"])
        self.assertEqual(forwarded["anthropic_version"], "vertex-2023-10-16")
        self.assertNotIn("model", forwarded)
        self.assertNotIn("input", forwarded)
        self.assertTrue(forwarded["system"][0]["text"].startswith("You are Codex"))
        self.assertEqual([t["name"] for t in forwarded["tools"]], ["exec_command", "write_stdin", "apply_patch"])
        # OpenCode is the thinking reference: no thinking, no output_config, no betas.
        self.assertNotIn("thinking", forwarded)
        self.assertNotIn("output_config", forwarded)
        self.assertFalse(any(m["role"] == "system" for m in forwarded["messages"]))
        self.assertIsNone(seen["beta"])

        row = ledger_rows(self.ledger, "cell-r")[-1]
        self.assertEqual((row["input_uncached"], row["output"], row["cache_read"], row["cache_write"]),
                         (11, 7, 4, 2))
        self.assertEqual(row["upstream_model"], "claude-sonnet-5-5")
        self.assertEqual(row["requested_model"], "claude-sonnet-5-5")
        record = row["cc_identity_stripped"]["responses"]
        self.assertEqual(record["presentation"], "responses")
        self.assertEqual(record["responses_dropped_tools"], ["web_search"])
        self.assertTrue(record["responses_cache_emulation"])
        self.assertEqual(record["responses_thinking"], "none")
        self.assertEqual(record["responses_reasoning_ignored"], "medium")
        self.assertEqual(len(record["responses_tools_sha"]), 16)
        self.assertEqual(len(record["responses_system_sha"]), 16)
        self.assertEqual(row["call_role"], "main")
        # Matches the OpenCode arm on Sonnet 5.5 (#196: thinking_sent=none).
        self.assertEqual(row["thinking_sent"], "none")
        self.assertEqual(row["thinking_mode"], "default")

    def test_accounting_matches_the_messages_and_chat_routes(self):
        """Same upstream usage -> identical ledger metering on all three routes."""
        # Same max_tokens everywhere: the call-role heuristic tags short,
        # tool-less calls as side calls, and that must not differ by route.
        _post(self.url("cell-m", "messages"),
              {"model": "claude-sonnet-5-5", "max_tokens": 32000,
               "messages": [{"role": "user", "content": "hi"}]})
        _post(self.url("cell-c", "chat/completions"),
              {"model": "claude-sonnet-5-5", "max_tokens": 32000,
               "messages": [{"role": "user", "content": "hi"}]})
        _post(self.url("cell-r", "responses"),
              {"model": "claude-sonnet-5-5", "input": "hi", "max_output_tokens": 32000})
        rows = {cell: ledger_rows(self.ledger, cell)[-1] for cell in ("cell-m", "cell-c", "cell-r")}
        meters = {cell: {k: row.get(k) for k in _METER_KEYS + ("call_role",)} for cell, row in rows.items()}
        self.assertEqual(meters["cell-r"], meters["cell-m"])
        self.assertEqual(meters["cell-r"], meters["cell-c"])
        self.assertEqual(read_call_totals(self.ledger, "cell-r"), read_call_totals(self.ledger, "cell-m"))

    def test_minted_reasoning_is_replayed_to_vertex(self):
        thinking = {"type": "thinking", "thinking": "Plan.", "signature": "sig-1"}
        body = codex_request()
        body["input"].insert(3, {"type": "reasoning", "id": "rs_1", "summary": [],
                                 "encrypted_content": encode_reasoning([thinking])})
        status, _ = _post(self.url("cell-t", "responses"), body)
        self.assertEqual(status, 200)
        forwarded = json.loads(self.httpd.seen[-1]["body"])
        assistant = [m for m in forwarded["messages"] if m["role"] == "assistant"][0]
        self.assertEqual(assistant["content"][0], thinking)

    def test_bad_requests_get_responses_errors(self):
        status, payload = _post(self.url("cell-b", "responses"), b"[1, 2]")
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(payload)["error"]["type"], "invalid_request_error")
        status, payload = _post(self.url("cell-b", "responses"), {"input": 7})
        self.assertEqual(status, 400)
        self.assertIn("input", json.loads(payload)["error"]["message"])
        self.assertEqual(self.httpd.seen, [])


class ResponsesEvidenceTests(ResponsesEndpointTests):
    def test_raw_codex_body_is_captured_before_translation(self):
        body = codex_request()
        raw = json.dumps(body).encode("utf-8")
        _post(self.url("cell-raw", "responses"), raw)
        _post(self.url("cell-raw", "responses"), raw)
        first = responses_capture_path(self.ledger, "cell-raw", 1)
        self.assertEqual(first.read_bytes(), raw)  # exactly what Codex sent
        self.assertTrue(responses_capture_path(self.ledger, "cell-raw", 2).is_file())
        record = ledger_rows(self.ledger, "cell-raw")[0]["cc_identity_stripped"]["responses"]
        self.assertEqual(record["responses_raw_request_file"], "cell-raw.responses/0001.request.json")
        instructions = body["instructions"]
        developer = body["input"][0]["content"][0]["text"]
        self.assertEqual(record["responses_raw_system_bytes"], len(f"{instructions}\n\n{developer}".encode()))
        self.assertEqual(record["responses_system_bytes"], record["responses_raw_system_bytes"])
        self.assertEqual(record["responses_raw_tools_bytes"],
                         len(json.dumps(body["tools"], sort_keys=True, separators=(",", ":")).encode()))
        self.assertGreater(record["responses_tools_bytes"], 0)

    def test_cache_miss_dumps_redacted_headers_and_hits_do_not(self):
        miss = json.loads(json.dumps(MESSAGE))
        miss["usage"]["cache_read_input_tokens"] = 0
        self.httpd.queue.append((json.dumps(miss).encode("utf-8"), False))
        _post(self.url("cell-h", "responses"), codex_request(),
              headers={"Authorization": "Bearer secret", "x-api-key": "k", "X-Probe": "1"})
        path = cache_miss_headers_path(self.ledger, "cell-h")
        lines = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual(len(lines), 1)
        line = lines[0]
        self.assertEqual(line["presentation"], "responses")
        self.assertEqual(line["usage"]["cache_read_input_tokens"], 0)
        request_headers = {k.lower(): v for k, v in line["request_headers"].items()}
        self.assertEqual(request_headers["authorization"], "<redacted>")
        self.assertEqual(request_headers["x-api-key"], "<redacted>")
        self.assertEqual(request_headers["x-probe"], "1")
        upstream = {k.lower(): v for k, v in line["upstream_headers"].items()}
        self.assertEqual(upstream["authorization"], "<redacted>")
        self.assertNotIn("anthropic-beta", upstream)  # no thinking wire, no betas
        self.assertEqual(line["responses_raw_request_file"], "cell-h.responses/0001.request.json")
        # MESSAGE has cache_read 4: a hit appends nothing.
        _post(self.url("cell-h", "responses"), codex_request())
        self.assertEqual(len(path.read_text().splitlines()), 1)


class ResponsesStreamTests(ResponsesEndpointTests):
    def test_stream_emits_responses_events_and_meters_like_messages(self):
        status, payload = _post(self.url("cell-s", "responses"), codex_request(stream=True))
        self.assertEqual(status, 200)
        events = responses_sse(payload)
        kinds = [e["type"] for e in events]
        self.assertEqual(kinds[0], "response.created")
        self.assertEqual(kinds[-1], "response.completed")
        self.assertIn("response.output_text.delta", kinds)
        final = events[-1]["response"]
        self.assertEqual([i["type"] for i in final["output"]], ["message", "function_call"])
        self.assertEqual(json.loads(final["output"][1]["arguments"]), {"cmd": "ls"})
        self.assertEqual(final["usage"]["input_tokens"], 17)
        self.assertEqual(final["usage"]["output_tokens"], 7)
        self.assertTrue(self.httpd.seen[-1]["path"].endswith(":streamRawPredict"))

        _post(self.url("cell-ms", "messages"),
              {"model": "claude-sonnet-5-5", "max_tokens": 64, "stream": True,
               "messages": [{"role": "user", "content": "hi"}]})
        stream_row = ledger_rows(self.ledger, "cell-s")[-1]
        messages_row = ledger_rows(self.ledger, "cell-ms")[-1]
        for key in ("input_uncached", "output", "cache_read", "cache_write", "usage"):
            self.assertEqual(stream_row.get(key), messages_row.get(key), key)

    def test_reasoning_from_the_stream_round_trips(self):
        thinking_stream = b"".join(
            b"event: " + e["type"].encode() + b"\ndata: " + json.dumps(e).encode() + b"\n\n" for e in [
                {"type": "message_start", "message": {"id": "msg_t", "usage": {"input_tokens": 5}}},
                {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}},
                {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "Hmm."}},
                {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "s9"}},
                {"type": "content_block_stop", "index": 0},
                {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}},
                {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "ok"}},
                {"type": "content_block_stop", "index": 1},
                {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 3}},
                {"type": "message_stop"},
            ])
        self.httpd.queue.append((thinking_stream, True))
        _, payload = _post(self.url("cell-rt", "responses"), codex_request(stream=True))
        reasoning = responses_sse(payload)[-1]["response"]["output"][0]
        self.assertEqual(reasoning["type"], "reasoning")
        blocks = decode_reasoning(reasoning["encrypted_content"])
        self.assertEqual(blocks, [{"type": "thinking", "thinking": "Hmm.", "signature": "s9"}])


class ResponsesUpstreamError(ResponsesEndpointTests):
    handler = _ErrorVertex

    def test_upstream_status_is_kept_with_a_responses_error_body(self):
        status, payload = _post(self.url("cell-e", "responses"), codex_request())
        self.assertEqual(status, 529)
        self.assertEqual(json.loads(payload), {"error": {
            "message": "Overloaded", "type": "overloaded_error", "code": "overloaded_error"}})
        row = ledger_rows(self.ledger, "cell-e")[-1]
        self.assertEqual(row["status"], 529)


if __name__ == "__main__":
    unittest.main()
