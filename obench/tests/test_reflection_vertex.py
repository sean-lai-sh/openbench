"""SEA-105: the reflection loop's Vertex routes (obench/reflection/vertex_models.py,
wire_proxy.py, smoke.py). A fake Vertex upstream stands in for Google; no
model calls, no credentials, no OpenCode binary."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from obench.reflection import smoke
from obench.reflection import trace as tr
from obench.reflection import vertex_models as vm
from obench.reflection.wire_proxy import WireProxy

DOC = Path(tr.__file__).with_name("TRACE_SCHEMA.md")
TOOLS_ANTHROPIC = [{"name": "bash", "description": "run", "input_schema": {"type": "object"}}]


def sse(*events):
    return b"".join(b"data: " + json.dumps(e).encode() + b"\n\n" for e in events)


ANTHROPIC_STREAM = sse(
    {"type": "message_start", "message": {"model": "claude-opus-5-5", "usage": {
        "input_tokens": 12, "cache_read_input_tokens": 1000, "cache_creation_input_tokens": 200, "output_tokens": 1}}},
    {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "plan"}},
    {"type": "message_delta", "usage": {"output_tokens": 300, "output_tokens_details": {"thinking_tokens": 120}}},
    {"type": "message_stop"})
GEMINI_STREAM = sse(
    {"candidates": [{"content": {"parts": [{"text": "**Plan** check", "thought": True}]}}], "modelVersion": "gemini-4-carbon",
     "usageMetadata": {"promptTokenCount": 50, "thoughtsTokenCount": 10}},
    {"candidates": [{"content": {"parts": [{"text": "A title"}]}}], "modelVersion": "gemini-4-carbon",
     "usageMetadata": {"promptTokenCount": 50, "candidatesTokenCount": 8, "thoughtsTokenCount": 64,
                       "totalTokenCount": 122}})
OPENAI_JSON = json.dumps({"model": "openai/gpt-oss-120b-maas", "choices": [{"message": {
    "role": "assistant", "content": "done", "reasoning_content": "think"}}],
    "usage": {"prompt_tokens": 84, "completion_tokens": 612,
              "completion_tokens_details": {"reasoning_tokens": 0}}}).encode()


class FakeVertex(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        return

    def do_POST(self):  # noqa: N802
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.server.seen.append({"path": self.path, "body": json.loads(raw),
                                 "headers": {k.lower(): v for k, v in self.headers.items()}})
        status, ctype, payload = self.server.reply(self.path)
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def default_reply(path):
    if "streamRawPredict" in path:
        return 200, "text/event-stream", ANTHROPIC_STREAM
    if "streamGenerateContent" in path:
        return 200, "text/event-stream", GEMINI_STREAM
    return 200, "application/json", OPENAI_JSON


class ProxyCase(unittest.TestCase):
    def setUp(self):
        self.vertex = ThreadingHTTPServer(("127.0.0.1", 0), FakeVertex)
        self.vertex.seen, self.vertex.reply = [], default_reply
        threading.Thread(target=self.vertex.serve_forever, daemon=True).start()
        self.addCleanup(self.vertex.server_close)
        self.addCleanup(self.vertex.shutdown)
        self.tmp = Path(tempfile.mkdtemp())
        self.wire = self.tmp / "wire.jsonl"
        host, port = self.vertex.server_address
        self.proxy = WireProxy("proj", self.wire, lambda: "tok", upstream_host=f"http://{host}:{port}")
        self.addCleanup(self.proxy.close)

    def post(self, path, body, headers=None):
        req = urllib.request.Request(self.proxy.base_url + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def records(self):
        return [json.loads(l) for l in self.wire.read_text().splitlines()] if self.wire.exists() else []


class Registry(unittest.TestCase):
    def test_exactly_the_three_vertex_models(self):
        self.assertEqual(set(vm.MODELS), {"gemini-4-carbon", "claude-opus-5-5", "gpt-oss-120b"})
        self.assertEqual({m.vertex_id for m in vm.MODELS.values()},
                         {"gemini-4-carbon", "claude-opus-5-5", "gpt-oss-120b-maas"})
        self.assertEqual({m.location for m in vm.MODELS.values()}, {"global"})
        for m in vm.MODELS.values():
            routed = json.dumps([m.key, m.vertex_id, m.client_ids, m.opencode_model, m.publisher]).lower()
            self.assertFalse(any(bad in routed for bad in ("sonnet", "qwen")), m.key)
            self.assertTrue(m.upstream_url("p", True).startswith("https://aiplatform.googleapis.com/v1/projects/p/locations/global/"))

    def test_no_fallback_for_missing_wrong_or_forbidden_names(self):
        for name in ("", None, "claude-opus", "opus", "claude-sonnet-5-5", "qwen3-coder", "gemini-4-argon",
                     "Claude-Opus-5-5", "gpt-oss-120b-maas"):
            with self.subTest(name=name), self.assertRaises(vm.UnknownModel):
                vm.resolve(name)

    def test_upstream_urls(self):
        p = "proj"
        self.assertEqual(vm.resolve("claude-opus-5-5").upstream_url(p, True),
                         "https://aiplatform.googleapis.com/v1/projects/proj/locations/global/publishers/anthropic/models/claude-opus-5-5:streamRawPredict")
        self.assertEqual(vm.resolve("gemini-4-carbon").upstream_url(p, False),
                         "https://aiplatform.googleapis.com/v1/projects/proj/locations/global/publishers/google/models/gemini-4-carbon:generateContent")
        self.assertEqual(vm.resolve("gpt-oss-120b").upstream_url(p, True),
                         "https://aiplatform.googleapis.com/v1/projects/proj/locations/global/endpoints/openapi/chat/completions")

    def test_opencode_config_enables_only_this_provider(self):
        for key in vm.MODELS:
            model = vm.resolve(key)
            cfg = vm.opencode_config(model, "http://127.0.0.1:9")
            pid = vm.provider_id(model)
            self.assertEqual(cfg["enabled_providers"], [pid])
            self.assertEqual(list(cfg["provider"]), [pid])
            self.assertEqual(cfg["model"], cfg["small_model"])
            self.assertEqual(cfg["model"], f"{pid}/{model.opencode_model}")
            self.assertTrue(cfg["provider"][pid]["options"]["baseURL"].startswith(f"http://127.0.0.1:9/m/{key}/"))

    def test_cost(self):
        opus = vm.resolve("claude-opus-5-5")
        usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_read_tokens": 1_000_000,
                 "cache_write_tokens": 1_000_000, "thinking_tokens": 500}
        self.assertEqual(vm.cost_usd(opus, usage), 4 + 20 + 0.2 + 5)
        carbon = vm.resolve("gemini-4-carbon")
        # Gemini: thinking billed as output, cached tokens out of the input count.
        self.assertEqual(vm.cost_usd(carbon, {"input_tokens": 1_000_000, "output_tokens": 0, "thinking_tokens": 1_000_000,
                                               "cache_read_tokens": 0}), 24.0)
        gptoss = vm.resolve("gpt-oss-120b")
        # The 2026-11-13 rerun: cached_tokens with no published cached price -> input rate, flagged estimate.
        detail = vm.cost_detail(gptoss, {"input_tokens": 12000, "output_tokens": 300, "cache_read_tokens": 9512})
        self.assertEqual(detail["basis"], ["list_unverified", "cache_read_at_input_rate"])
        self.assertTrue(detail["estimate"])
        self.assertAlmostEqual(detail["usd"], (12000 * 0.15 + 300 * 0.60) / 1e6)  # cached billed at the input rate
        self.assertEqual(vm.cost_usd(gptoss, {"input_tokens": 10, "output_tokens": 1}), round((10 * 0.15 + 0.60) / 1e6, 8))
        self.assertEqual(vm.cost_detail(opus, {"input_tokens": 1, "output_tokens": 1, "cache_read_tokens": 3})["basis"], ["list"])

    def test_docs_record_ids_regions_and_sources(self):
        text = Path(vm.__file__).with_name("VERTEX_MODELS.md").read_text()
        for m in vm.MODELS.values():
            self.assertIn(f"`{m.vertex_id}`", text)
        self.assertIn("openai/gpt-oss-120b-maas", text)
        self.assertEqual(len(re.findall(r"https://docs\.cloud\.google\.com|https://platform\.claude\.com", text)) >= 5, True)


class AnthropicRoute(ProxyCase):
    def test_stream_is_forwarded_to_opus_with_explicit_thinking_and_recorded(self):
        body = {"model": "claude-opus-5-5", "max_tokens": 32000, "stream": True, "temperature": 0.3,
                "tools": TOOLS_ANTHROPIC, "messages": [{"role": "user", "content": "go"}]}
        status, payload = self.post("/m/claude-opus-5-5/v1/messages", body, {"x-api-key": "openbench-proxy",
                                                                          "anthropic-beta": "fine-grained-tool-streaming-2025-05-14"})
        self.assertEqual(status, 200)
        self.assertEqual(payload, ANTHROPIC_STREAM)  # passed through unchanged
        seen = self.vertex.seen[-1]
        self.assertTrue(seen["path"].endswith("/publishers/anthropic/models/claude-opus-5-5:streamRawPredict"))
        self.assertEqual(seen["headers"]["authorization"], "Bearer tok")
        self.assertNotIn("x-api-key", set(seen["headers"]))
        self.assertEqual(seen["headers"].get("anthropic-beta"), "fine-grained-tool-streaming-2025-05-14")
        self.assertNotIn("model", seen["body"])
        self.assertEqual(seen["body"]["anthropic_version"], "vertex-2023-10-16")
        self.assertEqual(seen["body"]["thinking"], {"type": "adaptive", "display": "summarized"})
        self.assertNotIn("temperature", seen["body"])
        (rec,) = self.records()
        self.assertEqual((rec["call_role"], rec["upstream_model"], rec["route"]), ("main", "claude-opus-5-5", "claude-opus-5-5"))
        self.assertEqual(rec["response_usage"]["output_tokens_details"], {"thinking_tokens": 120})
        self.assertEqual(rec["thinking_enforced"], {"setting": {"type": "adaptive", "display": "summarized"}, "client": None,
                                                    "client_effort": None, "effort": "high", "removed": ["temperature"]})
        self.assertEqual(seen["body"]["output_config"], {"effort": "high"})
        self.assertGreater(rec["cost_usd"], 0)
        self.assertLessEqual(set(rec), Registry_documented_wire())

    def test_opus_effort_overrides_the_client_and_smoke_requires_it(self):
        body = {"model": "claude-opus-5-5", "stream": True, "tools": TOOLS_ANTHROPIC, "output_config": {"effort": "low"},
                "messages": [{"role": "user", "content": "go"}]}
        self.post("/m/claude-opus-5-5/v1/messages", body)
        (rec,) = self.records()
        self.assertEqual((rec["request"]["output_config"], rec["thinking_enforced"]["client_effort"]), ({"effort": "high"}, "low"))
        model = vm.resolve("claude-opus-5-5")
        cmd = ["opencode", "--model", vm.opencode_model_arg(model)]
        ok = smoke.checks(model, cmd, [rec], None, None, {"sha": "x"})["thinking_explicit"]
        self.assertTrue(ok["pass"])
        self.assertEqual(ok["setting"], {"thinking": {"type": "adaptive", "display": "summarized"},
                                         "output_config": {"effort": "high"}})
        stale = dict(rec, request={k: v for k, v in rec["request"].items() if k != "output_config"})
        self.assertFalse(smoke.checks(model, cmd, [stale], None, None, {"sha": "x"})["thinking_explicit"]["pass"])

    def test_start_snapshot_thinking_count_is_not_a_measurement(self):
        stream = sse({"type": "message_start", "message": {"model": "claude-opus-5-5", "usage": {
                          "input_tokens": 12, "output_tokens": 1, "output_tokens_details": {"thinking_tokens": 0}}}},
                     {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "summary"}},
                     {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 640}},
                     {"type": "message_stop"})
        self.vertex.reply = lambda path: (200, "text/event-stream", stream)
        body = {"model": "claude-opus-5-5", "stream": True, "tools": TOOLS_ANTHROPIC, "messages": [{"role": "user", "content": "go"}]}
        self.post("/m/claude-opus-5-5/v1/messages", body)
        (rec,) = self.records()
        self.assertEqual(rec["response_usage"], {"input_tokens": 12, "output_tokens": 640})
        self.assertEqual([e["event"] for e in rec["usage_events"]], ["message_start", "message_delta"])
        self.assertEqual(rec["usage_events"][0]["usage"]["output_tokens_details"], {"thinking_tokens": 0})  # kept raw
        usage = tr.usage_from_response("anthropic", rec["response_usage"], 1)
        self.assertEqual((usage["thinking_tokens"], usage["thinking_tokens_status"], usage["output_tokens_include_thinking"]),
                         (None, "unreported", True))
        model = vm.resolve("claude-opus-5-5")
        step = {"step": 1, "usage": usage, "thinking": {"text": "summary", "kind": "summary"}}
        self.assertTrue(smoke.usage_thinking(model, [step])["pass"])
        self.assertFalse(smoke.usage_thinking(model, [dict(step, thinking={"text": ""})])["pass"])

    def test_wrong_model_is_refused_without_an_upstream_call(self):
        status, payload = self.post("/m/claude-opus-5-5/v1/messages", {"model": "claude-sonnet-5-5", "messages": []})
        self.assertEqual(status, 400)
        self.assertIn("model_mismatch", payload.decode())
        status, _ = self.post("/m/claude-sonnet-5-5/v1/messages", {"model": "claude-sonnet-5-5", "messages": []})
        self.assertEqual(status, 404)
        status, _ = self.post("/v1/messages", {"model": "claude-opus-5-5", "messages": []})
        self.assertEqual(status, 404)
        self.assertEqual(self.vertex.seen, [])
        self.assertEqual(self.records(), [])

    def test_upstream_error_is_passed_through_and_recorded_without_usage(self):
        self.vertex.reply = lambda path: (529, "application/json", b'{"error": "overloaded"}')
        status, _ = self.post("/m/claude-opus-5-5/v1/messages", {"model": "claude-opus-5-5", "messages": []})
        self.assertEqual(status, 529)
        (rec,) = self.records()
        self.assertEqual((rec["status"], rec["response_usage"], rec["cost_usd"]), (529, None, None))


def Registry_documented_wire():
    section = DOC.read_text().split("## Wire record", 1)[1].split("\n## ", 1)[0]
    return {m.group(1) for m in re.finditer(r"^\| `([a-z_]+)` \|", section, re.M)}


class GeminiRoute(ProxyCase):
    def test_carbon_gets_explicit_thinking_level_and_summary_usage(self):
        body = {"contents": [{"role": "user", "parts": [{"text": "name this"}]}],
                "generationConfig": {"maxOutputTokens": 100, "thinkingConfig": {"thinkingBudget": 0}}}
        status, payload = self.post("/m/gemini-4-carbon/v1beta/models/gemini-4-carbon:streamGenerateContent?alt=sse",
                                    body, {"x-goog-api-key": "openbench-proxy"})
        self.assertEqual((status, payload), (200, GEMINI_STREAM))
        seen = self.vertex.seen[-1]
        self.assertTrue(seen["path"].endswith("/publishers/google/models/gemini-4-carbon:streamGenerateContent?alt=sse"))
        self.assertNotIn("x-goog-api-key", set(seen["headers"]))
        self.assertEqual(seen["body"]["generationConfig"]["thinkingConfig"],
                         {"thinkingLevel": "HIGH", "includeThoughts": True})  # the client's budget is replaced
        self.assertEqual(seen["body"]["generationConfig"]["maxOutputTokens"], 100)
        (rec,) = self.records()
        self.assertEqual((rec["call_role"], rec["upstream_model"]), ("side", "gemini-4-carbon"))  # no tools: title
        self.assertEqual(rec["response_usage"]["thoughtsTokenCount"], 64)  # last cumulative usageMetadata
        self.assertEqual(rec["thinking_enforced"]["client"], {"thinkingBudget": 0})

    def test_other_gemini_model_on_the_carbon_route_is_refused(self):
        status, _ = self.post("/m/gemini-4-carbon/v1beta/models/gemini-4-argon:generateContent", {"contents": []})
        self.assertEqual(status, 400)
        self.assertEqual(self.vertex.seen, [])


class OpenAIRoute(ProxyCase):
    def test_gpt_oss_body_model_reasoning_effort_and_zero_reasoning_tokens(self):
        body = {"model": "gpt-oss-120b-maas", "messages": [{"role": "user", "content": "go"}],
                "tools": [{"type": "function", "function": {"name": "bash", "parameters": {}}}]}
        status, payload = self.post("/m/gpt-oss-120b/v1/chat/completions", body, {"Authorization": "Bearer openbench-proxy"})
        self.assertEqual((status, payload), (200, OPENAI_JSON))
        seen = self.vertex.seen[-1]
        self.assertTrue(seen["path"].endswith("/locations/global/endpoints/openapi/chat/completions"))
        self.assertEqual(seen["headers"]["authorization"], "Bearer tok")
        self.assertEqual((seen["body"]["model"], seen["body"]["reasoning_effort"]), ("openai/gpt-oss-120b-maas", "high"))
        (rec,) = self.records()
        self.assertEqual(rec["response_usage"]["completion_tokens_details"]["reasoning_tokens"], 0)
        self.assertEqual(rec["upstream_model"], "openai/gpt-oss-120b-maas")

    def test_streaming_client_gets_a_stream_from_a_nonstream_upstream(self):
        doc = json.dumps({"model": "openai/gpt-oss-120b-maas", "choices": [{"index": 0, "finish_reason": "stop",
                          "message": {"role": "assistant", "content": "x"}}],
                          "usage": {"prompt_tokens": 5, "completion_tokens": 2,
                                    "completion_tokens_details": {"reasoning_tokens": 0}}}).encode()
        self.vertex.reply = lambda path: (200, "application/json", doc)
        status, payload = self.post("/m/gpt-oss-120b/v1/chat/completions",
                                    {"model": "openai/gpt-oss-120b-maas", "stream": True, "messages": []})
        sent = self.vertex.seen[-1]["body"]
        self.assertEqual((sent["stream"], "stream_options" in sent), (False, False))  # gpt-oss: upstream non-stream
        self.assertTrue(payload.startswith(b"data: ") and payload.endswith(b"data: [DONE]\n\n"))
        rec = self.records()[-1]
        self.assertEqual((rec["response_usage"]["prompt_tokens"], rec["upstream_stream"]), (5, False))


class SmokeRun(ProxyCase):
    """smoke.run end to end with OpenCode faked: outputs survive an undeletable temp HOME and a timeout."""

    def setUp(self):
        super().setUp()
        import os
        self.addCleanup(os.environ.pop, "GOOGLE_CLOUD_PROJECT", None)
        os.environ["GOOGLE_CLOUD_PROJECT"] = "proj"
        self.out = self.tmp / "smoke-out"

    def fake_opencode(self, timeout=False, solve=True):
        proxy_base = {}

        class P(smoke.WireProxy):
            def __init__(inner, project, wire_path, token, **kw):
                super().__init__(project, wire_path, token, upstream_host=self.proxy.upstream_host, **kw)
                proxy_base["url"] = inner.base_url

        import subprocess as real_sp
        real_run = real_sp.run

        def run(cmd, cwd, env, stdout, **kw):
            import os, subprocess as sp
            if cmd[0] == "bash":            # the task checker: run it for real on the workspace
                return real_run(cmd, cwd=cwd, env=env, stdout=stdout, **kw)
            home = Path(env["HOME"])
            stuck = home / ".cache" / "bun" / "pile"
            stuck.mkdir(parents=True)
            (stuck / "x.pile").write_text("x")
            os.chmod(stuck, 0o500)          # cleanup can't delete inside: the VM's Errno 39
            self.addCleanup(os.chmod, stuck, 0o700)
            if timeout:
                raise sp.TimeoutExpired(cmd, 1, stderr=b"slow")
            body = {"model": "claude-opus-5-5", "stream": True, "tools": TOOLS_ANTHROPIC, "messages": []}
            req = urllib.request.Request(proxy_base["url"] + "/m/claude-opus-5-5/v1/messages",
                                         data=json.dumps(body).encode(), method="POST",
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10).read()
            ev = [{"type": "step_start", "timestamp": 1, "sessionID": "s", "part": {"messageID": "m", "type": "step-start"}},
                  {"type": "step_finish", "timestamp": 2, "sessionID": "s", "part": {"messageID": "m", "type": "step-finish",
                   "reason": "stop", "cost": 0, "tokens": {"input": 1, "output": 1, "reasoning": 0, "cache": {"read": 0, "write": 0}}}}]
            stdout.write("".join(json.dumps(e) + "\n" for e in ev))
            import shutil as _sh
            if solve:
                    _sh.copy(smoke.DEFAULT_TASK / "solution" / "calculator.py", Path(cwd) / "calculator.py")  # agent fixes it
            import subprocess
            return subprocess.CompletedProcess(cmd, 0, None, "")
        return P, run

    def go(self, timeout=False):
        from unittest.mock import patch
        P, run = self.fake_opencode(timeout)
        argv = ["--model", "claude-opus-5-5", "--opencode", "/x/bin/sha/opencode", "--out", str(self.out)]
        with patch.object(smoke.oc, "verify_binary", return_value={"sha": "x"}), \
                patch("thesis.ab.vertex_anthropic_proxy.AdcToken", return_value=lambda: "tok"), \
                patch.object(smoke, "WireProxy", P), patch.object(smoke.subprocess, "run", run):
            return smoke.main(argv)

    def test_outputs_written_despite_cleanup_errors(self):
        code = self.go()
        summary = json.loads((self.out / "summary.json").read_text())
        self.assertEqual((summary["opencode_exit"], summary["opencode_timed_out"]), (0, False))
        self.assertTrue((self.out / "trace.jsonl").is_file())
        self.assertEqual(code, 0, summary)

    def test_unsolved_task_fails_the_smoke(self):
        from unittest.mock import patch
        P, run = self.fake_opencode(solve=False)
        argv = ["--model", "claude-opus-5-5", "--opencode", "/x/bin/sha/opencode", "--out", str(self.out)]
        with patch.object(smoke.oc, "verify_binary", return_value={"sha": "x"}), \
                patch("thesis.ab.vertex_anthropic_proxy.AdcToken", return_value=lambda: "tok"), \
                patch.object(smoke, "WireProxy", P), patch.object(smoke.subprocess, "run", run):
            code = smoke.main(argv)
        summary = json.loads((self.out / "summary.json").read_text())
        self.assertEqual(code, 1)
        self.assertNotEqual(summary["checks"]["task_solved"]["checker_exit"], 0)
        self.assertFalse(summary["checks"]["task_solved"]["pass"])
        self.assertTrue((self.out / "checker-output.txt").read_text())

    def test_timeout_still_writes_the_summary(self):
        self.assertEqual(self.go(timeout=True), 1)
        summary = json.loads((self.out / "summary.json").read_text())
        self.assertEqual((summary["opencode_exit"], summary["opencode_timed_out"]), (None, True))
        self.assertEqual((self.out / "opencode-stderr.txt").read_text(), "slow")


class ClientHangUp(ProxyCase):
    def test_client_disconnect_mid_stream_keeps_a_complete_record(self):
        import socket
        pad = [{"type": "content_block_delta", "delta": {"type": "text_delta", "text": "x" * 4000}} for _ in range(200)]
        start, end = ANTHROPIC_STREAM.split(b"\n\n", 1)[0] + b"\n\n", ANTHROPIC_STREAM.split(b"\n\n", 1)[1]
        big = start + sse(*pad) + end   # message_start ... 800 KB of deltas ... message_delta(usage), message_stop
        self.vertex.reply = lambda path: (200, "text/event-stream", big)
        body = json.dumps({"model": "claude-opus-5-5", "stream": True, "tools": TOOLS_ANTHROPIC, "messages": []}).encode()
        host, port = self.proxy.server.server_address[:2]
        sock = socket.create_connection((host, port))
        sock.sendall(b"POST /m/claude-opus-5-5/v1/messages HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
                     + f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
        sock.recv(2048)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")
        sock.close()                      # hang up (RST) while the proxy is still streaming
        import time
        for _ in range(100):
            if self.records():
                break
            time.sleep(0.05)
        (rec,) = self.records()
        self.assertEqual(rec["response_bytes"], len(big))                 # read to the end: not truncated
        self.assertEqual(rec["response_usage"]["output_tokens_details"], {"thinking_tokens": 120})  # final usage present
        self.assertEqual(rec["response_summary"]["finish_reasons"], [])  # (fixture has no stop_reason) still summarized
        self.assertGreater(rec["response_summary"]["text_chars"], 700_000)
        self.assertTrue(rec["client_disconnected"])


class Summary(unittest.TestCase):
    def test_openai_one_reasoning_step_with_no_tool_call_or_text(self):
        from obench.reflection.wire_proxy import response_summary
        oss = vm.resolve("gpt-oss-120b")
        raw = sse({"choices": [{"delta": {"reasoning_content": "We should look at calculator.py"}}]},
                  {"choices": [{"delta": {}, "finish_reason": "stop"}]},
                  {"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 9}}) + b"data: [DONE]\n\n"
        self.assertEqual(response_summary(oss, raw, True),
                         {"finish_reasons": ["stop"], "tool_calls": 0, "text_chars": 0, "reasoning_chars": 31,
                          "harmony_markers_in_text": False, "text_head": ""})
        harmony = sse({"choices": [{"delta": {"content": "<|channel|>commentary to=functions.bash <|message|>{}"}}]},
                      {"choices": [{"delta": {}, "finish_reason": "stop"}]})
        self.assertTrue(response_summary(oss, harmony, True)["harmony_markers_in_text"])
        raw = sse({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "bash"}}]}}]},
                  {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "{}"}}]}}]},
                  {"choices": [{"delta": {"tool_calls": [{"index": 1, "id": "c2", "function": {"name": "read"}}]}}]},
                  {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]})
        summary = response_summary(oss, raw, True)
        self.assertEqual((summary["tool_calls"], summary["finish_reasons"]), (3, ["tool_calls"]))  # (index, id) pairs

    def test_anthropic_and_gemini(self):
        from obench.reflection.wire_proxy import response_summary
        opus, carbon = vm.resolve("claude-opus-5-5"), vm.resolve("gemini-4-carbon")
        raw = sse({"type": "content_block_start", "content_block": {"type": "tool_use", "name": "bash"}},
                  {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "abc"}},
                  {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 3}})
        self.assertEqual(response_summary(opus, raw, True),
                         {"finish_reasons": ["tool_use"], "tool_calls": 1, "text_chars": 0, "reasoning_chars": 3})
        s = response_summary(carbon, GEMINI_STREAM, True)
        self.assertEqual((s["reasoning_chars"], s["text_chars"], s["tool_calls"]), (14, 7, 0))


class GptOssRepair(unittest.TestCase):
    TOOLS = [{"type": "function", "function": {"name": "read", "parameters": {"properties": {"filePath": {}, "offset": {}, "limit": {}}, "required": ["filePath"]}}},
             {"type": "function", "function": {"name": "write", "parameters": {"properties": {"filePath": {}, "content": {}}, "required": ["filePath", "content"]}}},
             {"type": "function", "function": {"name": "edit", "parameters": {"properties": {"filePath": {}, "oldString": {}, "newString": {}}, "required": ["filePath", "oldString", "newString"]}}},
             {"type": "function", "function": {"name": "bash", "parameters": {"properties": {"command": {}, "description": {}}, "required": ["command"]}}}]

    def req(self):
        return {"model": "openai/gpt-oss-120b-maas", "tools": self.TOOLS, "messages": []}

    def stream(self, reasoning, content="", finish="stop", tool_calls=None):
        delta = {"reasoning_content": reasoning}
        if content:
            delta["content"] = content
        if tool_calls:
            delta["tool_calls"] = tool_calls
        return sse({"id": "x", "model": "openai/gpt-oss-120b-maas", "choices": [{"index": 0, "delta": delta}]},
                   {"id": "x", "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]},
                   {"id": "x", "choices": [], "usage": {"prompt_tokens": 9, "completion_tokens": 30}}) + b"data: [DONE]\n\n"

    def doc(self, reasoning, content="", finish="stop"):
        message = {"role": "assistant", "content": content or None, "reasoning_content": reasoning}
        return json.dumps({"id": "x", "model": "openai/gpt-oss-120b-maas",
                           "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                           "usage": {"prompt_tokens": 9, "completion_tokens": 30}}).encode()

    def test_saturdays_case_json_at_end_of_reasoning(self):
        from obench.reflection import gptoss_repair as gr
        raw = self.stream('Let\'s read test file.{"filePath": "/app/test_calculator.py"}')
        out, rec = gr.repair(raw, True, self.req())
        self.assertEqual((rec["tool"], rec["method"], rec["source"]), ("read", "schema_match", "reasoning"))
        events = gr._parse_stream(out)
        calls = [c for e in events for ch in e.get("choices") or [] for c in (ch.get("delta") or {}).get("tool_calls") or []]
        self.assertEqual(calls[0]["function"], {"name": "read", "arguments": '{"filePath": "/app/test_calculator.py"}'})
        self.assertEqual([ch.get("finish_reason") for e in events for ch in e.get("choices") or [] if ch.get("finish_reason")],
                         ["tool_calls"])
        self.assertEqual(events[-1]["usage"], {"prompt_tokens": 9, "completion_tokens": 30})
        self.assertTrue(out.endswith(b"data: [DONE]\n\n"))

    def test_harmony_recipient_names_the_tool(self):
        from obench.reflection import gptoss_repair as gr
        text = 'Need to run tests.<|start|>assistant<|channel|>commentary to=functions.bash <|constrain|>json<|message|>{"command": "python3 -m unittest"}<|call|>'
        call = gr.extract_tool_call(text, self.req())
        self.assertEqual((call["name"], call["method"], call["arguments"]), ("bash", "harmony_recipient", {"command": "python3 -m unittest"}))
        doc = json.dumps({"model": "m", "choices": [{"message": {"role": "assistant", "content": "", "reasoning_content": text},
                                                     "finish_reason": "stop"}], "usage": {"prompt_tokens": 1}}).encode()
        out, rec = gr.repair(doc, False, self.req())
        msg = json.loads(out)["choices"][0]
        self.assertEqual((msg["finish_reason"], msg["message"]["tool_calls"][0]["function"]["name"]), ("tool_calls", "bash"))

    def test_left_alone_when_ambiguous_answered_or_already_structured(self):
        from obench.reflection import gptoss_repair as gr
        cases = [
            self.stream('Maybe {"filePath": "/a", "content": "x", "oldString": "y"}'),         # fits no tool
            self.stream('Consider {"filePath": "/a"} then more prose afterwards that is long enough'),  # not at the end
            self.stream('{"filePath": "/a"}', content="The bug is fixed; all tests pass."),      # real visible answer
            self.stream('{"filePath": "/a"}', finish="length"),                                   # not a stop
            self.stream('{"filePath": "/a"}', tool_calls=[{"index": 0, "id": "c", "function": {"name": "read"}}]),
            self.stream('All done.'),                                                              # no JSON at all
        ]
        for raw in cases:
            out, rec = gr.repair(raw, True, self.req())
            self.assertIsNone(rec)
            self.assertEqual(out, raw)
        out, rec = gr.repair(self.stream('{"filePath": "/a"}'), True, {"messages": []})  # request offered no tools
        self.assertIsNone(rec)
        # A tool we didn't offer is never mapped onto ours: passed under its own name (OpenCode answers "unknown
        # tool"), or left alone under "reject". Either way it is labelled.
        unknown = 'x<|channel|>commentary to=functions.delete_everything <|message|>{"path": "/"}'
        self.assertEqual(gr.extract_tool_call(unknown, self.req())["method"], "harmony_unknown_recipient")
        from unittest.mock import patch
        with patch.object(gr, "UNKNOWN_RECIPIENT", "reject"):
            self.assertIsNone(gr.extract_tool_call(unknown, self.req()))
        self.assertIsNone(gr.extract_tool_call('Set x to=5 then {"filePath": "/a", "content": "x", "oldString": "y"}',
                                               self.req()))  # "to=" in prose is not a recipient

    def test_nonstream_harmony_leak_from_the_diagnostic(self):
        """2026-11-16 diag, proxy_nonstream at effort high: finish tool_calls, no tool_calls, the call in content."""
        from obench.reflection import gptoss_repair as gr
        leak = '<|start|>assistant<|channel|>commentary to=repo_browser.print_tree code<|message|>{"path": "", "depth": 3}<|call|>'
        doc = json.dumps({"id": "x", "model": "openai/gpt-oss-120b-maas", "choices": [{"index": 0, "finish_reason": "tool_calls",
                          "message": {"role": "assistant", "content": leak, "reasoning_content": "Let's look at the repo."}}],
                          "usage": {"prompt_tokens": 9, "completion_tokens": 40}}).encode()
        out, rec = gr.repair(doc, False, self.req())
        self.assertEqual((rec["tool"], rec["method"], rec["known_tool"], rec["source"], rec["original_finish_reason"]),
                         ("repo_browser.print_tree", "harmony_unknown_recipient", False, "content", "tool_calls"))
        msg = json.loads(out)["choices"][0]["message"]
        self.assertEqual((msg["content"], json.loads(msg["tool_calls"][0]["function"]["arguments"])), (None, {"path": "", "depth": 3}))
        known = leak.replace("repo_browser.print_tree code", "functions.read code").replace('{"path": "", "depth": 3}', '{"filePath": "/app/a"}')
        out, rec = gr.repair(doc.replace(json.dumps(leak).encode()[1:-1], json.dumps(known).encode()[1:-1]), False, self.req())
        self.assertEqual((rec["tool"], rec["method"], rec["known_tool"]), ("read", "harmony_recipient", True))
        events = gr._parse_stream(gr.to_sse(out))   # what a streaming OpenCode then receives
        self.assertEqual(events[0]["choices"][0]["delta"]["reasoning_content"], "Let's look at the repo.")
        calls = [c for e in events for ch in e.get("choices") or [] for c in (ch.get("delta") or {}).get("tool_calls") or []]
        self.assertEqual((calls[0]["index"], calls[0]["function"]["name"]), (0, "read"))
        self.assertEqual(events[-1]["usage"], {"prompt_tokens": 9, "completion_tokens": 40})


class GptOssDiag(unittest.TestCase):
    def test_runs_every_variant_and_saves_raw_bytes(self):
        import os
        from unittest.mock import patch
        from obench.reflection import gptoss_diag as gd
        out = Path(tempfile.mkdtemp()) / "diag"
        self.addCleanup(shutil.rmtree, out.parent, True)
        seen = []

        def call(url, body, token):
            seen.append((url, body))
            if url.endswith("/completions") and not url.endswith("chat/completions"):
                return 200, json.dumps({"choices": [{"text": 'x<|channel|>commentary to=functions.read <|message|>{"filePath": "/app/a"}<|call|>',
                                                     "finish_reason": "stop"}]}).encode(), 0.1
            if body.get("stream"):
                return 200, GptOssRepair().stream("We have a codebase. Let's explore."), 0.1
            return 400, b'{"error": "skip_special_tokens unsupported"}', 0.1
        with patch.dict(os.environ, {"GOOGLE_CLOUD_PROJECT": "proj"}), \
                patch("thesis.ab.vertex_anthropic_proxy.AdcToken", return_value=lambda: "tok"), patch.object(gd, "call", call):
            self.assertEqual(gd.main(["--out", str(out)]), 0)
        summary = json.loads((out / "summary.json").read_text())
        rows = {r["variant"]: r for r in summary["rows"]}
        self.assertEqual(len(rows), 8)
        self.assertEqual(rows["proxy_stream"]["finish_reasons"], ["stop"])
        self.assertTrue(rows["raw_completions"]["recoverable_tool_call"])
        self.assertIn("unsupported", rows["keep_special"]["error_head"])
        self.assertTrue((out / "proxy_stream.raw").read_bytes().startswith(b"data:"))
        self.assertIn("/projects/<project>/", summary["url"])
        self.assertEqual(json.loads((out / "proxy_stream.request.json").read_text())["reasoning_effort"], "high")
        ts = json.loads((out / "tools_in_system.request.json").read_text())
        self.assertIn("filePath", ts["messages"][0]["content"])
        self.assertNotIn("stream_options", json.loads((out / "proxy_nonstream.request.json").read_text()))
        with self.assertRaises(SystemExit):
            gd.main(["--out", str(out.parent / "results" / "x")])


class RouteRepairInProxy(ProxyCase):
    def test_gpt_oss_text_tool_call_reaches_opencode_as_tool_calls(self):
        from obench.reflection import gptoss_repair as gr
        from obench.reflection.wire_proxy import route_truncated
        upstream = GptOssRepair().doc('Let\'s read test file.{"filePath": "/app/test_calculator.py"}')
        self.vertex.reply = lambda path: (200, "application/json", upstream)
        body = {"model": "gpt-oss-120b-maas", "stream": True, "tools": GptOssRepair.TOOLS, "messages": [{"role": "user", "content": "fix"}]}
        status, payload = self.post("/m/gpt-oss-120b/v1/chat/completions", body)
        self.assertEqual(status, 200)
        calls = [c for e in gr._parse_stream(payload) for ch in e.get("choices") or [] for c in (ch.get("delta") or {}).get("tool_calls") or []]
        self.assertEqual(calls[0]["function"]["name"], "read")
        (rec,) = self.records()
        self.assertEqual((rec["route_repair"]["tool"], rec["response_summary"]["tool_calls"]), ("read", 1))
        self.assertEqual(rec["upstream_response_summary"]["tool_calls"], 0)
        self.assertEqual(rec["response_usage"]["completion_tokens"], 30)
        self.assertIsNone(route_truncated([rec]))
        from obench.reflection.wire_proxy import classify_4xx, route_repair_counts, upstream_4xx
        main = lambda i, st: {"call_index": i, "status": st, "call_role": "main"}
        recovered = [main(1, 200), main(2, 429), main(3, 429), main(4, 200), {"call_index": 5, "status": 400, "call_role": "side"}]
        self.assertEqual(classify_4xx(recovered), {"breaking": [], "retried": {"429": 2, "400": 1}})
        ended = [main(1, 200), main(2, 429), main(3, 400)]
        self.assertEqual(classify_4xx(ended), {"breaking": [main(2, 429), main(3, 400)], "retried": {}})
        self.assertEqual(upstream_4xx([rec, {"call_index": 7, "status": 429, "call_role": "main"}, {"status": 500}]),
                         [{"call_index": 7, "status": 429, "call_role": "main"}])
        side = {"call_role": "side", "status": 200, "route_repair": {"applied": True}}
        self.assertEqual(route_repair_counts([rec, side, {"status": 500}]),
                         {"model_calls": 1, "tool_call_turns": 1, "route_repairs": 1, "unknown_recipient_calls": 0})

    def test_unrepairable_stop_is_route_truncated(self):
        from obench.reflection.wire_proxy import route_truncated
        self.vertex.reply = lambda path: (200, "application/json", GptOssRepair().doc("I think I am done thinking."))
        body = {"model": "gpt-oss-120b-maas", "stream": True, "tools": GptOssRepair.TOOLS, "messages": []}
        self.post("/m/gpt-oss-120b/v1/chat/completions", body)
        (rec,) = self.records()
        self.assertIsNone(rec["route_repair"])
        self.assertEqual(rec["upstream_response_summary"]["finish_reasons"], ["stop"])  # filled with no repair too
        raw = (self.wire.parent / rec["upstream_raw"]).read_bytes()
        self.assertIn(b"I think I am done thinking.", raw)
        truncated = route_truncated([rec])
        self.assertEqual(truncated["finish_reasons"], ["stop"])
        model = vm.resolve("gpt-oss-120b")
        result = smoke.checks(model, ["x", "--model", vm.opencode_model_arg(model)], [rec], None, None, {"sha": "x"}, 1)
        self.assertFalse(result["not_route_truncated"]["pass"])
        self.assertFalse(result["task_solved"]["pass"])

    def test_unknown_recipient_leak_is_passed_and_counted_or_truncated(self):
        from unittest.mock import patch
        from obench.reflection import gptoss_repair as gr
        from obench.reflection.wire_proxy import route_repair_counts, route_truncated
        leak = '<|start|>assistant<|channel|>commentary to=repo_browser.print_tree code<|message|>{"path": "", "depth": 3}<|call|>'
        self.vertex.reply = lambda path: (200, "application/json", GptOssRepair().doc("Explore.", content=leak, finish="tool_calls"))
        body = {"model": "gpt-oss-120b-maas", "stream": True, "tools": GptOssRepair.TOOLS, "messages": []}
        _, payload = self.post("/m/gpt-oss-120b/v1/chat/completions", body)
        calls = [c for e in gr._parse_stream(payload) for ch in e.get("choices") or [] for c in (ch.get("delta") or {}).get("tool_calls") or []]
        self.assertEqual(calls[0]["function"]["name"], "repo_browser.print_tree")  # OpenCode answers "unknown tool"
        rec = self.records()[-1]
        self.assertEqual(route_repair_counts([rec])["unknown_recipient_calls"], 1)
        self.assertIsNone(route_truncated([rec]))
        with patch.object(gr, "UNKNOWN_RECIPIENT", "reject"):
            self.post("/m/gpt-oss-120b/v1/chat/completions", body)
        rec = self.records()[-1]
        self.assertIsNone(rec["route_repair"])
        self.assertEqual(route_truncated([rec])["kind"], "harmony_leak")

    def test_other_models_are_never_rewritten(self):
        self.assertFalse(vm.resolve("claude-opus-5-5").repair_text_tool_calls)
        self.assertFalse(vm.resolve("gemini-4-carbon").repair_text_tool_calls)
        self.assertTrue(vm.resolve("gpt-oss-120b").repair_text_tool_calls)


class EndToEnd(ProxyCase):
    """Proxy wire records + an OpenCode event stream -> a complete trace and passing smoke checks."""

    def events(self):
        def ev(kind, ts, msg, **part):
            ptype = {"step_start": "step-start", "step_finish": "step-finish"}.get(kind, kind)
            return {"type": kind, "timestamp": ts, "sessionID": "s",
                    "part": {"messageID": msg, "type": ptype, **part}}
        return [ev("step_start", 1, "m1"), ev("reasoning", 2, "m1", text="plan", time={"start": 1, "end": 2}),
                ev("step_finish", 3, "m1", reason="tool-calls", cost=0.0, tokens={"input": 1, "output": 1, "reasoning": 0,
                                                                                    "cache": {"read": 0, "write": 0}}),
                ev("step_start", 4, "m2"), ev("text", 5, "m2", text="done", time={"start": 4, "end": 5}),
                ev("step_finish", 6, "m2", reason="stop", cost=0.0, tokens={"input": 1, "output": 1, "reasoning": 0,
                                                                              "cache": {"read": 0, "write": 0}})]

    def test_opus_smoke_checks_pass(self):
        model = vm.resolve("claude-opus-5-5")
        body = {"model": "claude-opus-5-5", "stream": True, "tools": TOOLS_ANTHROPIC,
                "messages": [{"role": "user", "content": "go"}]}
        for _ in range(2):
            self.post("/m/claude-opus-5-5/v1/messages", body)
        self.post("/m/claude-opus-5-5/v1/messages", {"model": "claude-opus-5-5", "stream": True,
                                                     "messages": [{"role": "user", "content": "title"}]})  # side
        wires = self.records()
        records = tr.build_trace(tr.parse_events([json.dumps(e) for e in self.events()]), wires,
                                 cost_fn=lambda rec: (vm.cost_usd(model, rec["usage"]), "reflection.vertex_models"))
        self.assertEqual([r["usage"]["thinking_tokens"] for r in records], [120, 120])
        self.assertEqual(records[0]["request"]["thinking_setting"]["value"], {"type": "adaptive", "display": "summarized"})
        cmd = ["opencode", "run", "--format", "json", "--thinking", "--model", vm.opencode_model_arg(model), "x"]
        result = smoke.checks(model, cmd, wires, records, None, {"sha": "x"}, checker_exit=0)
        self.assertEqual({k: v["pass"] for k, v in result.items()}, dict.fromkeys(result, True))
        self.assertEqual((result["traced"]["wire_calls"], result["traced"]["main_calls"]), (3, 2))

    def gptoss_records(self, reasoning_text):
        model = vm.resolve("gpt-oss-120b")
        body = {"model": "gpt-oss-120b-maas", "messages": [{"role": "user", "content": "go"}],
                "tools": [{"type": "function", "function": {"name": "bash", "parameters": {}}}]}
        self.post("/m/gpt-oss-120b/v1/chat/completions", body)
        def ev(kind, ts, **part):
            ptype = {"step_start": "step-start", "step_finish": "step-finish"}.get(kind, kind)
            return {"type": kind, "timestamp": ts, "sessionID": "s", "part": {"messageID": "m1", "type": ptype, **part}}
        events = [ev("step_start", 1)]
        if reasoning_text is not None:
            events.append(ev("reasoning", 2, text=reasoning_text, time={"start": 1, "end": 2}))
        events.append(ev("step_finish", 3, reason="stop", cost=0.0,
                         tokens={"input": 1, "output": 1, "reasoning": 0, "cache": {"read": 0, "write": 0}}))
        counter = lambda text: (len(text.split()), "computed: fake o200k_harmony (test)")
        return model, tr.build_trace(tr.parse_events([json.dumps(e) for e in events]), self.records(),
                                     count_thinking_tokens=counter)

    def test_gpt_oss_reported_zero_with_text_passes_flagged(self):
        text = "We need to check the failing test first."
        model, records = self.gptoss_records(text)
        step = records[0]
        self.assertEqual(step["usage"]["thinking_tokens"], 0)  # the usage value, never replaced
        self.assertEqual(step["request"]["thinking_setting"], {"explicit": True, "field": "reasoning_effort",
                                                               "value": "high"})
        thinking = step["thinking"]
        self.assertEqual((thinking["flag"], thinking["chars"], thinking["text"]), ("reported_zero_text_present", len(text), text))
        self.assertEqual((thinking["tokens_counted"], thinking["tokens_counted_by"]),
                         (8, "computed: fake o200k_harmony (test)"))
        check = smoke.usage_thinking(model, records)
        self.assertTrue(check["pass"])
        self.assertEqual(check["flags"], ["reported_zero_text_present"])
        self.assertFalse(check["comparable_with_other_models"])
        self.assertEqual(check["per_step"][0]["thinking_tokens"], 0)

    def test_gpt_oss_usage_without_any_reasoning_field_passes_flagged(self):
        """The 2026-11-13 VM smoke: usage had only prompt/completion/total tokens."""
        self.vertex.reply = lambda path: (200, "application/json", json.dumps({
            "model": "openai/gpt-oss-120b-maas", "choices": [{"message": {"role": "assistant", "content": "ok",
                                                                         "reasoning_content": "x" * 888}}],
            "usage": {"prompt_tokens": 84, "completion_tokens": 612, "total_tokens": 696}}).encode())
        text = "x" * 888
        model, records = self.gptoss_records(text)
        step = records[0]
        self.assertIsNone(step["usage"]["thinking_tokens"])          # absent, recorded as null
        self.assertIsNone(step["usage"]["thinking_tokens_field"])
        self.assertEqual((step["thinking"]["flag"], step["thinking"]["chars"]), ("reported_absent_text_present", 888))
        check = smoke.usage_thinking(model, records)
        self.assertTrue(check["pass"])
        self.assertEqual(check["flags"], ["reported_absent_text_present"])
        self.assertIsNone(check["per_step"][0]["thinking_tokens"])
        cmd = ["opencode", "--model", vm.opencode_model_arg(model)]
        result = smoke.checks(model, cmd, self.records(), records, None, {"sha": "x"})
        self.assertTrue(result["model"]["pass"], result["model"])     # served "openai/gpt-oss-120b-maas" accepted
        self.assertEqual(result["model"]["served"], ["openai/gpt-oss-120b-maas"])

    def test_served_model_matching(self):
        oss, opus = vm.resolve("gpt-oss-120b"), vm.resolve("claude-opus-5-5")
        self.assertTrue(vm.served_matches(oss, "openai/gpt-oss-120b-maas"))
        self.assertTrue(vm.served_matches(oss, "gpt-oss-120b-maas"))
        self.assertFalse(vm.served_matches(oss, "openai/gpt-oss-20b-maas"))
        self.assertTrue(vm.served_matches(opus, "claude-opus-5-5"))
        self.assertFalse(vm.served_matches(opus, "claude-sonnet-5-5"))
        self.assertFalse(vm.served_matches(opus, None))

    def test_opus_and_carbon_still_need_a_reported_count(self):
        records = [{"step": 1, "usage": {"thinking_tokens": None}, "thinking": {"text": "summary", "chars": 7}}]
        for key in ("claude-opus-5-5", "gemini-4-carbon"):
            self.assertFalse(smoke.usage_thinking(vm.resolve(key), records)["pass"])

    def test_gpt_oss_fails_only_when_reasoning_text_is_missing_or_empty(self):
        for text in (None, "", "   "):
            with self.subTest(text=text):
                self.wire.unlink(missing_ok=True)
                model, records = self.gptoss_records(text)
                check = smoke.usage_thinking(model, records)
                self.assertFalse(check["pass"])
                self.assertIsNone(records[0]["thinking"]["flag"])
                self.assertEqual(records[0]["thinking"]["chars"], 0)

    def test_other_models_keep_the_usage_rule_and_counter_is_optional(self):
        opus = vm.resolve("claude-opus-5-5")
        records = [{"step": 1, "usage": {"thinking_tokens": 0}, "thinking": {"text": "", "kind": "none", "chars": 0}}]
        self.assertTrue(smoke.usage_thinking(opus, records)["pass"])  # Opus: a reported 0 is fine
        self.assertTrue(smoke.usage_thinking(opus, records)["comparable_with_other_models"])
        self.assertNotIn("claude-opus-5-5", vm.THINKING_TOKENS_FROM_TEXT)
        self.assertNotIn("gemini-4-carbon", vm.THINKING_TOKENS_FROM_TEXT)
        import builtins
        from unittest.mock import patch
        real_import = builtins.__import__
        def no_tiktoken(name, *a, **k):
            if name == "tiktoken":
                raise ImportError("no tiktoken")
            return real_import(name, *a, **k)
        with patch("builtins.__import__", no_tiktoken):
            count, label = vm.count_o200k_harmony("some reasoning")
        self.assertIsNone(count)
        self.assertTrue(label.startswith("unavailable:"))

    def test_checks_fail_on_wrong_command_model_or_missing_usage(self):
        model = vm.resolve("claude-opus-5-5")
        self.post("/m/claude-opus-5-5/v1/messages", {"model": "claude-opus-5-5", "stream": True,
                                                     "tools": TOOLS_ANTHROPIC, "messages": []})
        wires = self.records()
        result = smoke.checks(model, ["opencode", "--model", "vertex-claude-opus-5-5/claude-sonnet-5-5"], wires,
                              None, "usage_missing (step 1)", None)
        self.assertFalse(result["model"]["pass"])
        self.assertFalse(result["traced"]["pass"])
        self.assertFalse(result["pin"]["pass"])

    def test_out_dir_and_child_env(self):
        for bad in ("/tmp/x/results/smoke", "/home/u/openbench/data/x"):
            with self.subTest(bad=bad), self.assertRaises(SystemExit):
                smoke.check_out_dir(Path(bad))
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-should-not-leak", "OPENCODE_CONFIG": "/x"}):
            env = smoke.child_env(vm.resolve("gpt-oss-120b"), "http://127.0.0.1:1", self.tmp)
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("OPENCODE_CONFIG", env)
        self.assertEqual(json.loads(env["OPENCODE_CONFIG_CONTENT"])["enabled_providers"], ["vertex-gpt-oss-120b"])


if __name__ == "__main__":
    unittest.main()
