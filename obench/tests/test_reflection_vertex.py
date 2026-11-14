"""SEA-105: the reflection loop's Vertex routes (obench/reflection/vertex_models.py,
wire_proxy.py, smoke.py). A fake Vertex upstream stands in for Google; no
model calls, no credentials, no OpenCode binary."""

from __future__ import annotations

import json
import re
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
        self.assertEqual(seen["body"]["thinking"], {"type": "adaptive"})
        self.assertNotIn("temperature", seen["body"])
        (rec,) = self.records()
        self.assertEqual((rec["call_role"], rec["upstream_model"], rec["route"]), ("main", "claude-opus-5-5", "claude-opus-5-5"))
        self.assertEqual(rec["response_usage"]["output_tokens_details"], {"thinking_tokens": 120})
        self.assertEqual(rec["thinking_enforced"], {"setting": {"type": "adaptive"}, "client": None,
                                                    "removed": ["temperature"]})
        self.assertGreater(rec["cost_usd"], 0)
        self.assertLessEqual(set(rec), Registry_documented_wire())

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

    def test_streaming_asks_for_usage(self):
        chunks = sse({"model": "openai/gpt-oss-120b-maas", "choices": [{"delta": {"content": "x"}}]},
                     {"model": "openai/gpt-oss-120b-maas", "choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 2,
                      "completion_tokens_details": {"reasoning_tokens": 0}}}) + b"data: [DONE]\n\n"
        self.vertex.reply = lambda path: (200, "text/event-stream", chunks)
        self.post("/m/gpt-oss-120b/v1/chat/completions", {"model": "openai/gpt-oss-120b-maas", "stream": True,
                                                          "messages": []})
        self.assertEqual(self.vertex.seen[-1]["body"]["stream_options"], {"include_usage": True})
        self.assertEqual(self.records()[-1]["response_usage"]["prompt_tokens"], 5)


class SmokeRun(ProxyCase):
    """smoke.run end to end with OpenCode faked: outputs survive an undeletable temp HOME and a timeout."""

    def setUp(self):
        super().setUp()
        import os
        self.addCleanup(os.environ.pop, "GOOGLE_CLOUD_PROJECT", None)
        os.environ["GOOGLE_CLOUD_PROJECT"] = "proj"
        self.out = self.tmp / "smoke-out"

    def fake_opencode(self, timeout=False):
        proxy_base = {}

        class P(smoke.WireProxy):
            def __init__(inner, project, wire_path, token, **kw):
                super().__init__(project, wire_path, token, upstream_host=self.proxy.upstream_host, **kw)
                proxy_base["url"] = inner.base_url

        def run(cmd, cwd, env, stdout, **kw):
            import os, subprocess as sp
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

    def test_timeout_still_writes_the_summary(self):
        self.assertEqual(self.go(timeout=True), 1)
        summary = json.loads((self.out / "summary.json").read_text())
        self.assertEqual((summary["opencode_exit"], summary["opencode_timed_out"]), (None, True))
        self.assertEqual((self.out / "opencode-stderr.txt").read_text(), "slow")


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
        self.assertEqual(records[0]["request"]["thinking_setting"]["value"], {"type": "adaptive"})
        cmd = ["opencode", "run", "--format", "json", "--thinking", "--model", vm.opencode_model_arg(model), "x"]
        result = smoke.checks(model, cmd, wires, records, None, {"sha": "x"})
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
