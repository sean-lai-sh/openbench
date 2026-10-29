"""Anthropic and OpenAI endpoints on the Vertex proxy, plus call-role tags.

Vertex is a local stub. Token totals for a recorded OpenCode ledger stay on
the pre-change score.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from thesis.ab.run_ab import apply_cell_meter
from thesis.ab.vertex_anthropic_proxy import (
    classify_call_role,
    read_call_totals,
    start_proxy,
    summarize_call_totals,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "thesis" / "ab" / "fixtures" / "anthropic"
LEDGER_FIXTURE = FIXTURE / "opencode-cell-ledger.jsonl"
SCORE_FIXTURE = FIXTURE / "opencode-cell-score.json"

MESSAGE = {
    "id": "msg_tool",
    "type": "message",
    "role": "assistant",
    "model": "claude-sonnet-5-5",
    "stop_reason": "tool_use",
    "content": [
        {"type": "text", "text": "running"},
        {"type": "tool_use", "id": "toolu_1", "name": "bash", "input": {"cmd": "ls"}},
    ],
    "usage": {
        "input_tokens": 11,
        "output_tokens": 7,
        "cache_read_input_tokens": 4,
        "cache_creation_input_tokens": 2,
        "cache_creation": {
            "ephemeral_5m_input_tokens": 2,
            "ephemeral_1h_input_tokens": 0,
        },
    },
}


def _event(name: str, obj: dict) -> bytes:
    body = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    return b"event: " + name.encode("ascii") + b"\ndata: " + body + b"\n\n"


STREAM = b"".join([
    _event("message_start", {
        "type": "message_start",
        "message": {
            "id": "msg_s",
            "type": "message",
            "role": "assistant",
            "content": [],
            "model": "claude-sonnet-5-5",
            "usage": {
                "input_tokens": 11,
                "output_tokens": 1,
                "cache_read_input_tokens": 4,
                "cache_creation_input_tokens": 2,
            },
        },
    }),
    _event("content_block_start", {
        "type": "content_block_start",
        "index": 0,
        "content_block": {"type": "text", "text": ""},
    }),
    _event("content_block_delta", {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "text_delta", "text": "running"},
    }),
    _event("content_block_stop", {"type": "content_block_stop", "index": 0}),
    _event("content_block_start", {
        "type": "content_block_start",
        "index": 1,
        "content_block": {"type": "tool_use", "id": "toolu_1", "name": "bash", "input": {}},
    }),
    _event("content_block_delta", {
        "type": "content_block_delta",
        "index": 1,
        "delta": {"type": "input_json_delta", "partial_json": "{\"cmd\":\"ls\"}"},
    }),
    _event("content_block_stop", {"type": "content_block_stop", "index": 1}),
    _event("message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": "tool_use"},
        "usage": {"output_tokens": 7},
    }),
    _event("message_stop", {"type": "message_stop"}),
])


def _write_chunked(handler, payload: bytes) -> None:
    step = 48
    for index in range(0, len(payload), step):
        part = payload[index:index + step]
        handler.wfile.write(f"{len(part):X}\r\n".encode("ascii"))
        handler.wfile.write(part)
        handler.wfile.write(b"\r\n")
        handler.wfile.flush()
    handler.wfile.write(b"0\r\n\r\n")
    handler.wfile.flush()


class _Vertex(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):  # noqa: N802 - stdlib name
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        self.server.seen.append({
            "path": self.path,
            "body": raw,
            "beta": self.headers.get("anthropic-beta"),
            "auth": self.headers.get("Authorization"),
        })
        if self.server.queue:
            payload, stream = self.server.queue.pop(0)
        else:
            stream = self.path.endswith(":streamRawPredict")
            payload = self.server.stream_body if stream else self.server.json_body
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream" if stream else "application/json")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        try:
            _write_chunked(self, payload)
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            return

    def log_message(self, fmt, *args):
        return


def _post(url, body, headers=None):
    request = urllib.request.Request(
        url, data=body if isinstance(body, bytes) else json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _sse_json(payload: bytes) -> list:
    found = []
    for block in payload.decode("utf-8").split("\n\n"):
        for line in block.splitlines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            found.append(None if data == "[DONE]" else json.loads(data))
    return found


def _usage(inp, out, cache_read, cache_write) -> bytes:
    return json.dumps({
        "id": "msg",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": "ok"}],
        "stop_reason": "end_turn",
        "usage": {
            "input_tokens": inp,
            "output_tokens": out,
            "cache_read_input_tokens": cache_read,
            "cache_creation_input_tokens": cache_write,
        },
    }).encode("utf-8")


class VertexHarnessApiTests(unittest.TestCase):
    def setUp(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Vertex)
        self.httpd.seen = []
        self.httpd.queue = []
        self.httpd.json_body = json.dumps(MESSAGE).encode("utf-8")
        self.httpd.stream_body = STREAM
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.ledger = Path(tempfile.mkdtemp())
        host, port = self.httpd.server_address
        self.proxy = start_proxy(
            "proj", token="tok", upstream=f"http://{host}:{port}",
            ledger_dir=self.ledger, route_by_request=True,
        )
        self.addCleanup(self.proxy.close)
        self.addCleanup(self.httpd.shutdown)
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(lambda: self.thread.join(timeout=2))

    def test_anthropic_messages_forwards_tools_cache_and_meters_usage(self):
        body = {
            "model": "claude-sonnet-5-5",
            "max_tokens": 128,
            "temperature": 0.2,
            "system": [{
                "type": "text",
                "text": "You are a coding agent. " + ("work " * 40),
                "cache_control": {"type": "ephemeral"},
            }],
            "tools": [{
                "name": "bash",
                "description": "run",
                "input_schema": {"type": "object", "properties": {"cmd": {"type": "string"}}},
                "cache_control": {"type": "ephemeral"},
            }],
            "messages": [
                {"role": "user", "content": "list files"},
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "I'll check."},
                        {"type": "tool_use", "id": "toolu_0", "name": "bash", "input": {"cmd": "ls"}},
                    ],
                },
                {
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": "toolu_0",
                        "content": "a.py",
                    }],
                },
            ],
        }
        status, payload = _post(
            self.proxy.base_url + "/c/cell-a/v1/messages",
            body,
            {"anthropic-beta": "prompt-caching-2024-07-31"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(payload), MESSAGE)
        seen = self.httpd.seen[-1]
        self.assertTrue(seen["path"].endswith(
            "/models/claude-sonnet-5-5:rawPredict",
        ))
        self.assertEqual(seen["auth"], "Bearer tok")
        self.assertEqual(seen["beta"], "prompt-caching-2024-07-31")
        forwarded = json.loads(seen["body"])
        self.assertEqual(forwarded["anthropic_version"], "vertex-2023-10-16")
        self.assertNotIn("model", forwarded)
        self.assertNotIn("temperature", forwarded)
        self.assertEqual(forwarded["system"][0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(forwarded["tools"][0]["input_schema"]["properties"]["cmd"]["type"], "string")
        self.assertEqual(forwarded["tools"][0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(forwarded["messages"][1]["content"][1]["type"], "tool_use")
        self.assertEqual(forwarded["messages"][2]["content"][0]["type"], "tool_result")
        row = json.loads((self.ledger / "cell-a.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(row["usage"]["input_tokens"], 11)
        self.assertEqual(row["usage"]["cache_read_input_tokens"], 4)
        self.assertEqual(row["usage"]["cache_creation_input_tokens"], 2)
        self.assertEqual(row["usage"]["cache_creation"]["ephemeral_5m_input_tokens"], 2)
        self.assertEqual(row["input_uncached"], 11)
        self.assertEqual(row["output"], 7)
        self.assertEqual(row["cache_read"], 4)
        self.assertEqual(row["cache_write"], 2)
        self.assertNotIn("prompt_tokens", row["usage"])
        self.assertEqual(row["call_role"], "main")
        self.assertEqual(row["call_role_reason"], "heuristic:main")

    def test_anthropic_stream_passes_tool_use_and_cache_fields_through(self):
        status, payload = _post(
            self.proxy.base_url + "/c/cell-s/v1/messages",
            {
                "model": "claude-opus-5-5",
                "max_tokens": 128,
                "stream": True,
                "tools": [{"name": "bash", "input_schema": {"type": "object"}}],
                "messages": [{"role": "user", "content": "list files"}],
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload, STREAM)
        self.assertIn(b"tool_use", payload)
        self.assertIn(b"cache_read_input_tokens", payload)
        self.assertIn(b"input_json_delta", payload)
        self.assertTrue(self.httpd.seen[-1]["path"].endswith(
            "/models/claude-opus-5-5:streamRawPredict",
        ))
        row = json.loads((self.ledger / "cell-s.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(row["usage"], {
            "input_tokens": 11,
            "output_tokens": 7,
            "cache_read_input_tokens": 4,
            "cache_creation_input_tokens": 2,
        })
        self.assertEqual(row["input_uncached"], 11)
        self.assertEqual(row["output"], 7)
        self.assertEqual(row["cache_read"], 4)
        self.assertEqual(row["cache_write"], 2)
        self.assertNotIn("bash", (self.ledger / "cell-s.jsonl").read_text(encoding="utf-8"))

    def test_openai_chat_completions_translates_tools_and_cache_fields(self):
        body = {
            "model": "anthropic/claude-sonnet-5-5",
            "temperature": 0.4,
            "max_tokens": 64,
            "messages": [
                {"role": "system", "content": [{
                    "type": "text",
                    "text": "You are a coding agent. " + ("work " * 40),
                    "cache_control": {"type": "ephemeral"},
                }]},
                {"role": "user", "content": "list files"},
                {
                    "role": "assistant",
                    "content": "I'll check.",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "bash", "arguments": "{\"cmd\":\"ls\"}"},
                        },
                        {
                            "id": "call_2",
                            "type": "function",
                            "function": {"name": "bash", "arguments": "{\"cmd\":\"pwd\"}"},
                        },
                    ],
                },
                {"role": "tool", "tool_call_id": "call_1", "content": "a.py"},
                {"role": "tool", "tool_call_id": "call_2", "content": "/tmp"},
            ],
            "tools": [{
                "type": "function",
                "function": {
                    "name": "bash",
                    "description": "run",
                    "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}},
                },
                "cache_control": {"type": "ephemeral"},
            }],
            "tool_choice": {"type": "function", "function": {"name": "bash"}},
        }
        status, payload = _post(
            self.proxy.base_url + "/c/cell-o/v1/chat/completions",
            body,
        )
        self.assertEqual(status, 200)
        parsed = json.loads(payload)
        message = parsed["choices"][0]["message"]
        self.assertEqual(message["content"], "running")
        self.assertEqual(message["tool_calls"][0]["function"]["name"], "bash")
        self.assertEqual(json.loads(message["tool_calls"][0]["function"]["arguments"]), {"cmd": "ls"})
        self.assertEqual(parsed["choices"][0]["finish_reason"], "tool_calls")
        self.assertEqual(parsed["model"], "claude-sonnet-5-5")
        usage = parsed["usage"]
        self.assertEqual(usage["prompt_tokens"], 17)
        self.assertEqual(usage["completion_tokens"], 7)
        self.assertEqual(usage["prompt_tokens_details"]["cached_tokens"], 4)
        self.assertEqual(usage["prompt_tokens_details"]["cache_write_tokens"], 2)
        self.assertEqual(usage["cache_read_input_tokens"], 4)
        self.assertEqual(usage["cache_creation_input_tokens"], 2)
        self.assertEqual(usage["cache_creation"]["ephemeral_5m_input_tokens"], 2)
        seen = self.httpd.seen[-1]
        self.assertTrue(seen["path"].endswith("/models/claude-sonnet-5-5:rawPredict"))
        forwarded = json.loads(seen["body"])
        self.assertEqual(forwarded["anthropic_version"], "vertex-2023-10-16")
        self.assertNotIn("model", forwarded)
        self.assertNotIn("temperature", forwarded)
        self.assertEqual(forwarded["system"][0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(forwarded["tools"][0]["name"], "bash")
        self.assertIn("input_schema", forwarded["tools"][0])
        self.assertEqual(forwarded["tools"][0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(forwarded["tool_choice"], {"type": "tool", "name": "bash"})
        assistant = forwarded["messages"][1]["content"]
        self.assertEqual([block["type"] for block in assistant], ["text", "tool_use", "tool_use"])
        tool_results = forwarded["messages"][2]["content"]
        self.assertEqual(
            [block["tool_use_id"] for block in tool_results],
            ["call_1", "call_2"],
        )
        row = json.loads((self.ledger / "cell-o.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(row["usage"]["input_tokens"], 11)
        self.assertNotIn("prompt_tokens", row["usage"])
        self.assertEqual(row["input_uncached"], 11)
        self.assertEqual(row["cache_read"], 4)
        self.assertEqual(row["cache_write"], 2)
        self.assertEqual(row["upstream_model"], "claude-sonnet-5-5")
        self.assertEqual(row["requested_model"], "anthropic/claude-sonnet-5-5")
        self.assertEqual(row["endpoint_location"], "global")

    def test_openai_stream_emits_text_tool_calls_and_cache_usage(self):
        status, payload = _post(
            self.proxy.base_url + "/v1/chat/completions",
            {
                "model": "claude-opus-5-5",
                "stream": True,
                "max_tokens": 32,
                "messages": [{"role": "user", "content": "list files"}],
                "tools": [{
                    "type": "function",
                    "function": {"name": "bash", "parameters": {"type": "object"}},
                }],
            },
        )
        self.assertEqual(status, 200)
        self.assertNotIn(b"message_start", payload)
        self.assertNotIn(b"input_json_delta", payload)
        events = _sse_json(payload)
        self.assertIn(None, events)
        chunks = [event for event in events if isinstance(event, dict)]
        text = "".join(
            event["choices"][0]["delta"].get("content") or ""
            for event in chunks
        )
        self.assertEqual(text, "running")
        names = []
        arguments = []
        for event in chunks:
            calls = event["choices"][0]["delta"].get("tool_calls") or []
            for call in calls:
                function = call.get("function") or {}
                if function.get("name"):
                    names.append(function["name"])
                    self.assertEqual(call["index"], 0)
                if function.get("arguments"):
                    arguments.append(function["arguments"])
        self.assertEqual(names, ["bash"])
        self.assertIn("ls", "".join(arguments))
        finished = [event for event in chunks if event["choices"][0]["finish_reason"]]
        self.assertEqual(finished[-1]["choices"][0]["finish_reason"], "tool_calls")
        usage = finished[-1]["usage"]
        self.assertEqual(usage["cache_read_input_tokens"], 4)
        self.assertEqual(usage["cache_creation_input_tokens"], 2)
        self.assertEqual(usage["prompt_tokens_details"]["cached_tokens"], 4)
        self.assertTrue(self.httpd.seen[-1]["path"].endswith(":streamRawPredict"))

    def test_request_model_selects_sonnet_or_opus_only_when_routing_is_on(self):
        status, _payload = _post(
            self.proxy.base_url + "/v1/messages",
            {"model": "claude-sonnet-5-5", "max_tokens": 8, "messages": [{"role": "user", "content": "a"}]},
        )
        self.assertEqual(status, 200)
        self.assertIn("/models/claude-sonnet-5-5:rawPredict", self.httpd.seen[-1]["path"])
        status, _payload = _post(
            self.proxy.base_url + "/v1/chat/completions",
            {"model": "openai/claude-opus-5-5@default", "messages": [{"role": "user", "content": "b"}]},
        )
        self.assertEqual(status, 200)
        self.assertIn("/models/claude-opus-5-5:rawPredict", self.httpd.seen[-1]["path"])

        host, port = self.httpd.server_address
        pinned = start_proxy(
            "proj", model="claude-opus-5-5", token="tok",
            upstream=f"http://{host}:{port}", route_by_request=False,
        )
        self.addCleanup(pinned.close)
        status, _payload = _post(
            pinned.base_url + "/v1/messages",
            {"model": "claude-sonnet-5-5", "max_tokens": 16, "messages": [{"role": "user", "content": "c"}]},
        )
        self.assertEqual(status, 200)
        self.assertIn("/models/claude-opus-5-5:rawPredict", self.httpd.seen[-1]["path"])
        status, _payload = _post(
            pinned.base_url + "/v1/chat/completions",
            {"model": "claude-sonnet-5-5", "messages": [{"role": "user", "content": "d"}]},
        )
        self.assertEqual(status, 200)
        self.assertIn("/models/claude-opus-5-5:rawPredict", self.httpd.seen[-1]["path"])

        routed = start_proxy(
            "proj", model="claude-sonnet-5-5", token="tok",
            upstream=f"http://{host}:{port}", route_by_request=True,
        )
        self.addCleanup(routed.close)
        status, _payload = _post(
            routed.base_url + "/v1/chat/completions",
            {"model": "gpt-4o", "messages": [{"role": "user", "content": "e"}]},
        )
        self.assertEqual(status, 200)
        self.assertIn("/models/claude-sonnet-5-5:rawPredict", self.httpd.seen[-1]["path"])

    def test_route_env_selects_the_request_model_and_openai_defaults_max_tokens(self):
        host, port = self.httpd.server_address
        with patch.dict(os.environ, {"OBENCH_VERTEX_ROUTE_BY_REQUEST": "1"}):
            routed = start_proxy(
                "proj", model="claude-opus-5-5", token="tok",
                upstream=f"http://{host}:{port}",
            )
        self.addCleanup(routed.close)
        status, _payload = _post(
            routed.base_url + "/v1/chat/completions",
            {"model": "claude-sonnet-5-5", "messages": [{"role": "user", "content": "hi"}]},
        )
        self.assertEqual(status, 200)
        self.assertIn("/models/claude-sonnet-5-5:rawPredict", self.httpd.seen[-1]["path"])
        self.assertEqual(json.loads(self.httpd.seen[-1]["body"])["max_tokens"], 8192)
        plain = start_proxy(
            "proj", model="claude-opus-5-5", token="tok",
            upstream=f"http://{host}:{port}",
        )
        self.addCleanup(plain.close)
        status, _payload = _post(
            plain.base_url + "/v1/messages",
            {
                "model": "claude-sonnet-5-5",
                "max_tokens": 8,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        self.assertEqual(status, 200)
        self.assertIn("/models/claude-opus-5-5:rawPredict", self.httpd.seen[-1]["path"])

    def test_ledger_records_requested_model_and_vertex_location(self):
        host, port = self.httpd.server_address
        pinned = start_proxy(
            "proj", model="claude-sonnet-5-5", location="global", token="tok",
            upstream=f"http://{host}:{port}", ledger_dir=self.ledger,
            route_by_request=False,
        )
        self.addCleanup(pinned.close)
        status, _payload = _post(
            pinned.base_url + "/c/rewrite/v1/messages",
            {"model": "claude-opus-5-5", "max_tokens": 8, "messages": [{"role": "user", "content": "hi"}]},
        )
        self.assertEqual(status, 200)
        self.assertIn("/locations/global/publishers/anthropic/models/claude-sonnet-5-5:", self.httpd.seen[-1]["path"])
        row = json.loads((self.ledger / "rewrite.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(row["requested_model"], "claude-opus-5-5")
        self.assertEqual(row["upstream_model"], "claude-sonnet-5-5")
        self.assertEqual(row["endpoint_location"], "global")

        shifted = start_proxy(
            "proj", model="claude-sonnet-5-5", location="europe-west4", token="tok",
            upstream=f"http://{host}:{port}", ledger_dir=self.ledger,
            route_by_request=False,
        )
        self.addCleanup(shifted.close)
        status, _payload = _post(
            shifted.base_url + "/c/shifted/v1/messages",
            {"model": "claude-sonnet-5-5", "max_tokens": 8, "messages": [{"role": "user", "content": "hi"}]},
        )
        self.assertEqual(status, 200)
        self.assertIn("/locations/europe-west4/", self.httpd.seen[-1]["path"])
        shifted_row = json.loads((self.ledger / "shifted.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(shifted_row["endpoint_location"], "europe-west4")
        self.assertEqual(shifted_row["upstream_model"], "claude-sonnet-5-5")


class CallRoleTests(unittest.TestCase):
    def test_header_wins_and_heuristics_cover_side_calls(self):
        title = {
            "max_tokens": 32,
            "system": "You are a title generator. Never use tools.",
            "messages": [{"role": "user", "content": "hello"}],
        }
        self.assertEqual(
            classify_call_role(title, "main"),
            {"call_role": "main", "call_role_reason": "header"},
        )
        self.assertEqual(
            classify_call_role({"max_tokens": 8, "messages": []}, "side:title"),
            {"call_role": "side", "call_role_reason": "header", "call_role_detail": "title"},
        )
        self.assertEqual(
            classify_call_role({"max_tokens": 8, "messages": []}, "SUMMARY"),
            {"call_role": "side", "call_role_reason": "header", "call_role_detail": "summary"},
        )
        self.assertEqual(classify_call_role(title, None)["call_role_detail"], "title")
        self.assertEqual(classify_call_role(title, None)["call_role_reason"], "heuristic:title")
        summary = {
            "max_tokens": 400,
            "system": "Summarize the conversation in one paragraph.",
            "messages": [{"role": "user", "content": "thread"}],
        }
        self.assertEqual(
            classify_call_role(summary, None),
            {"call_role": "side", "call_role_reason": "heuristic:summary", "call_role_detail": "summary"},
        )
        memory = {
            "max_tokens": 200,
            "system": "Extract the relevant memories from the session.",
            "messages": [{"role": "user", "content": "notes"}],
        }
        self.assertEqual(classify_call_role(memory, None)["call_role_detail"], "memory")
        helper = {
            "max_completion_tokens": 16,
            "messages": [{"role": "system", "content": "You are a helper model."}, {"role": "user", "content": "x"}],
        }
        self.assertEqual(
            classify_call_role(helper, None),
            {"call_role": "side", "call_role_reason": "heuristic:helper", "call_role_detail": "helper"},
        )
        subagent = {
            "max_tokens": 8000,
            "tools": [{"name": "bash"}],
            "system": "You are a subagent. Finish the subtask.",
            "messages": [{"role": "user", "content": "go"}],
        }
        self.assertEqual(
            classify_call_role(subagent, None),
            {"call_role": "side", "call_role_reason": "heuristic:subagent", "call_role_detail": "subagent"},
        )
        long_title = dict(title, max_tokens=8000)
        self.assertEqual(classify_call_role(long_title, None)["call_role"], "main")
        with_tools = dict(title, tools=[{"name": "bash"}])
        self.assertEqual(classify_call_role(with_tools, None)["call_role"], "main")
        tiny = {"max_tokens": 8, "messages": [{"role": "user", "content": "ping"}]}
        self.assertEqual(
            classify_call_role(tiny, None),
            {"call_role": "side", "call_role_reason": "heuristic:short-no-tools"},
        )
        self.assertEqual(classify_call_role(tiny, "banana")["call_role_reason"], "heuristic:short-no-tools")
        hidden = {
            "max_tokens": 128,
            "tools": [{"name": "bash"}],
            "messages": [{
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "t", "content": "you are a subagent"}],
            }],
        }
        self.assertEqual(classify_call_role(hidden, None)["call_role"], "main")

    def test_ledger_records_the_role_and_splits_all_from_main(self):
        def usage_for(raw: bytes) -> bytes:
            if b"MARKER-TITLE" in raw:
                return _usage(4, 1, 0, 0)
            if b"MARKER-SUMMARY" in raw:
                return _usage(6, 2, 0, 0)
            if b"MARKER-MEMORY" in raw:
                return _usage(8, 3, 1, 1)
            if b"MARKER-SUB" in raw:
                return _usage(9, 4, 2, 2)
            return _usage(100, 40, 10, 5)

        class _Marked(_Vertex):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                self.server.seen.append({"path": self.path, "body": raw})
                payload = usage_for(raw)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Marked)
        httpd.seen = []
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
        calls = [
            ({
                "model": "claude-opus-5-5",
                "max_tokens": 8000,
                "system": "You are a coding agent. " + ("work " * 40),
                "tools": [{"name": "bash", "input_schema": {"type": "object"}}],
                "messages": [{"role": "user", "content": "MARKER-MAIN"}],
            }, None),
            ({
                "model": "claude-opus-5-5",
                "max_tokens": 32,
                "system": "You are a title generator. Never use tools. MARKER-TITLE",
                "messages": [{"role": "user", "content": "hello"}],
            }, None),
            ({
                "model": "claude-opus-5-5",
                "max_tokens": 400,
                "system": "Summarize the conversation. MARKER-SUMMARY",
                "messages": [{"role": "user", "content": "thread"}],
            }, None),
            ({
                "model": "claude-opus-5-5",
                "max_tokens": 8000,
                "tools": [{"name": "bash", "input_schema": {"type": "object"}}],
                "system": "You are a coding agent.",
                "messages": [{"role": "user", "content": "MARKER-MEMORY"}],
            }, {"X-OB-Call-Role": "memory"}),
            ({
                "model": "claude-opus-5-5",
                "max_tokens": 8000,
                "tools": [{"name": "bash", "input_schema": {"type": "object"}}],
                "system": "You are a subagent. MARKER-SUB",
                "messages": [{"role": "user", "content": "go"}],
            }, None),
        ]
        for body, headers in calls:
            status, _payload = _post(proxy.base_url + "/c/roles/v1/messages", body, headers)
            self.assertEqual(status, 200)
        rows = [
            json.loads(line)
            for line in (ledger / "roles.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(
            [(row["call_role"], row.get("call_role_detail"), row["call_role_reason"]) for row in rows],
            [
                ("main", None, "heuristic:main"),
                ("side", "title", "heuristic:title"),
                ("side", "summary", "heuristic:summary"),
                ("side", "memory", "header"),
                ("side", "subagent", "heuristic:subagent"),
            ],
        )
        self.assertEqual(rows[0]["input_uncached"], 100)
        self.assertEqual(rows[1]["output"], 1)
        self.assertEqual(rows[3]["cache_read"], 1)
        self.assertEqual(rows[4]["cache_write"], 2)
        totals = read_call_totals(ledger, "roles")
        self.assertEqual(totals["all"], {
            "calls": 5, "input_uncached": 127, "output": 50, "cache_read": 13, "cache_write": 8,
        })
        self.assertEqual(totals["main"], {
            "calls": 1, "input_uncached": 100, "output": 40, "cache_read": 10, "cache_write": 5,
        })
        scored = {
            "tokens_input_uncached": 3,
            "tokens_output": 3,
            "tokens_cache_read": 3,
            "tokens_cache_write": 3,
            "token_basis": "vendor_split",
            "usage_raw": [{"input": 3, "output": 3}],
        }
        apply_cell_meter(scored, {"ledger_dir": str(ledger), "cell_id": "roles"})
        self.assertEqual(scored["tokens_input_uncached"], 127)
        self.assertEqual(scored["tokens_output"], 50)
        self.assertEqual(scored["tokens_cache_read"], 13)
        self.assertEqual(scored["tokens_cache_write"], 8)
        self.assertEqual(scored["tokens_main_input_uncached"], 3)
        self.assertEqual(scored["tokens_main_output"], 3)
        self.assertEqual(scored["tokens_main_calls"], 1)
        self.assertEqual(scored["token_basis_main"], "vendor_split")


class OpenCodeScoreRegressionTests(unittest.TestCase):
    def test_recorded_ledger_scores_the_same_numbers(self):
        golden = json.loads(SCORE_FIXTURE.read_text(encoding="utf-8"))
        ledger = Path(tempfile.mkdtemp())
        shutil.copy(LEDGER_FIXTURE, ledger / "opencode-recorded.jsonl")
        row = apply_cell_meter({}, {"ledger_dir": str(ledger), "cell_id": "opencode-recorded"})
        for key, expected in golden.items():
            if key == "requests_cost_usd":
                self.assertAlmostEqual(row[key], expected, places=6)
            else:
                self.assertEqual(row[key], expected, key)
        recorded = [
            json.loads(line)
            for line in LEDGER_FIXTURE.read_text(encoding="utf-8").splitlines()
        ]
        totals = summarize_call_totals(recorded)
        self.assertEqual(totals["main"], totals["all"])
        self.assertEqual(totals["all"]["input_uncached"], golden["tokens_input_uncached"])
        self.assertEqual(totals["all"]["output"], golden["tokens_output"])
        self.assertEqual(totals["all"]["cache_read"], golden["tokens_cache_read"])
        self.assertEqual(totals["all"]["cache_write"], golden["tokens_cache_write"])
        self.assertEqual(totals["all"]["calls"], golden["tokens_proxy_calls"])
        self.assertNotIn("call_role", recorded[0])

    def test_replaying_recorded_responses_keeps_the_same_score(self):
        golden = json.loads(SCORE_FIXTURE.read_text(encoding="utf-8"))
        recorded = [
            json.loads(line)
            for line in LEDGER_FIXTURE.read_text(encoding="utf-8").splitlines()
        ]
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Vertex)
        httpd.seen = []
        httpd.json_body = b"{}"
        httpd.stream_body = b""
        httpd.queue = [
            ((FIXTURE / "messages.json").read_bytes(), False),
            ((FIXTURE / "sdk-1.2-message-stream.sse").read_bytes(), True),
            ((FIXTURE / "sdk-2.0-beta-message-stream.sse").read_bytes(), True),
        ]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        host, port = httpd.server_address
        ledger = Path(tempfile.mkdtemp())
        proxy = start_proxy(
            "proj", model="claude-opus-5-5", token="tok",
            upstream=f"http://{host}:{port}", ledger_dir=ledger,
            route_by_request=False,
        )
        self.addCleanup(proxy.close)
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        self.addCleanup(lambda: thread.join(timeout=2))
        request = {
            "model": "claude-opus-5-5",
            "max_tokens": 128000,
            "system": [{
                "type": "text",
                "text": "You are a coding agent. " + ("work " * 40),
                "cache_control": {"type": "ephemeral"},
            }],
            "tools": [{
                "name": "bash",
                "input_schema": {"type": "object"},
                "cache_control": {"type": "ephemeral"},
            }],
            "messages": [{"role": "user", "content": "go"}],
        }
        for stream in (False, True, True):
            body = dict(request, stream=True) if stream else request
            status, _payload = _post(proxy.base_url + "/c/replay/v1/messages", body)
            self.assertEqual(status, 200)
        rows = [
            json.loads(line)
            for line in (ledger / "replay.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual([row["usage"] for row in rows], [row["usage"] for row in recorded])
        self.assertTrue(all(row["upstream_model"] == "claude-opus-5-5" for row in rows))
        forwarded = json.loads(httpd.seen[0]["body"])
        self.assertEqual(forwarded["tools"][0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(forwarded["system"][0]["cache_control"], {"type": "ephemeral"})
        self.assertNotIn("model", forwarded)
        scored = apply_cell_meter({}, {"ledger_dir": str(ledger), "cell_id": "replay"})
        for key, expected in golden.items():
            if key == "requests_cost_usd":
                self.assertAlmostEqual(scored[key], expected, places=6)
            else:
                self.assertEqual(scored[key], expected, key)
        self.assertNotIn("tokens_main_input_uncached", scored)


if __name__ == "__main__":
    unittest.main()
