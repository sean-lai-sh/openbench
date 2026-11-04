"""Responses API <-> Anthropic Messages translation (thesis/ab/responses_api.py).

Pure translation: no proxy, no network. The proxy round trip is in
test_vertex_proxy_responses.py.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from thesis.ab.responses_api import (
    REASONING_ENVELOPE,
    ResponsesContext,
    ResponsesError,
    ResponsesStream,
    anthropic_message_to_responses,
    decode_reasoning,
    encode_reasoning,
    responses_error_bytes,
    responses_to_anthropic,
    responses_usage,
)

FIXTURES = Path(__file__).resolve().parents[2] / "thesis" / "ab" / "fixtures" / "responses"


def codex_request() -> dict:
    return json.loads((FIXTURES / "codex-request.json").read_text(encoding="utf-8"))


def usage_fixture() -> dict:
    return json.loads((FIXTURES / "usage.json").read_text(encoding="utf-8"))


def sse(*events) -> bytes:
    out = b""
    for obj in events:
        out += b"event: " + obj["type"].encode() + b"\ndata: " + json.dumps(obj).encode() + b"\n\n"
    return out


def parse_sse(chunks) -> list:
    text = b"".join(chunks).decode("utf-8")
    found = []
    for block in text.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data:"):
                found.append(json.loads(line[5:].strip()))
    return found


THINKING = {"type": "thinking", "thinking": "Check the tests first.", "signature": "sig-abc"}
PI_THINKING = {"type": "adaptive", "display": "summarized",
               "block_binding": {"prefix_mismatch_behavior": "drop_block"}}


def real(messages: list) -> list:
    """Messages without Pi's mid-conversation effort markers."""
    return [m for m in messages if m.get("role") != "system"]


def strip_cache(value):
    if isinstance(value, dict):
        return {k: strip_cache(v) for k, v in value.items() if k != "cache_control"}
    if isinstance(value, list):
        return [strip_cache(v) for v in value]
    return value


class RequestTranslation(unittest.TestCase):
    def setUp(self):
        self.body, self.ctx = responses_to_anthropic(codex_request())

    def test_instructions_and_developer_items_become_system(self):
        texts = [block["text"] for block in self.body["system"]]
        self.assertTrue(texts[0].startswith("You are Codex"))
        self.assertIn("<permissions instructions>", texts[1])
        self.assertTrue(all(m["role"] in {"user", "assistant"} for m in real(self.body["messages"])))

    def test_late_developer_items_stay_in_place_and_system_is_stable(self):
        request = codex_request()
        request["input"].append({"type": "message", "role": "developer",
                                 "content": [{"type": "input_text", "text": "Context is 80% full."}]})
        body, ctx = responses_to_anthropic(request)
        self.assertEqual(strip_cache(body["system"]), strip_cache(self.body["system"]))
        self.assertEqual(ctx.system_sha, self.ctx.system_sha)
        self.assertEqual(ctx.inline_developer, 1)
        last = real(body["messages"])[-1]["content"][-1]
        self.assertEqual(last["text"], "<developer>\nContext is 80% full.\n</developer>")

    def test_tool_calls_and_outputs_pair_up_and_roles_alternate(self):
        messages = real(self.body["messages"])
        roles = [m["role"] for m in messages]
        for left, right in zip(roles, roles[1:]):
            self.assertNotEqual(left, right)
        assistant = messages[1]["content"]
        self.assertEqual([b["type"] for b in assistant], ["text", "tool_use"])
        self.assertEqual(assistant[1]["id"], "toolu_1")
        self.assertEqual(assistant[1]["input"], {"cmd": "ls", "yield_time_ms": 1000})
        result = strip_cache(messages[2]["content"][0])
        self.assertEqual(result, {"type": "tool_result", "tool_use_id": "toolu_1",
                                  "content": "app.py\ntest_app.py\n"})
        custom = messages[3]["content"][0]
        self.assertEqual(custom["name"], "apply_patch")
        self.assertEqual(custom["input"], {"input": "*** Begin Patch\n*** End Patch"})
        self.assertEqual(messages[4]["content"][0]["tool_use_id"], "toolu_2")

    def test_tools_map_and_hosted_tools_are_dropped_and_recorded(self):
        names = [tool["name"] for tool in self.body["tools"]]
        self.assertEqual(names, ["exec_command", "write_stdin", "apply_patch"])
        self.assertEqual(self.body["tools"][0]["input_schema"]["required"], ["cmd"])
        self.assertEqual(self.body["tools"][2]["input_schema"]["required"], ["input"])
        self.assertEqual(self.ctx.custom_tools, frozenset({"apply_patch"}))
        self.assertEqual(self.ctx.dropped_tools, ("web_search",))
        self.assertEqual(self.body["tool_choice"], {"type": "auto", "disable_parallel_tool_use": True})

    def test_reasoning_effort_becomes_the_pi_thinking_wire(self):
        """Same fields as the Pi arm's captured Claude request (pi-ai effort messages)."""
        self.assertEqual(self.body["thinking"], PI_THINKING)
        self.assertEqual(self.body["output_config"], {"effort": "low"})  # fixed, cached
        marker = {"role": "system", "content": [], "output_config": {"effort": "medium"}}
        self.assertEqual(self.body["messages"][-1], marker)
        for index, message in enumerate(self.body["messages"]):
            if message["role"] == "assistant":
                self.assertEqual(self.body["messages"][index - 1], marker)
        self.assertEqual(self.ctx.thinking, "adaptive:medium")
        self.assertEqual(self.ctx.betas, ("mid-conversation-output-config-2026-07-01",
                                          "thinking-binding-controls-2026-08-01"))
        for effort, expected in (("minimal", "low"), ("low", "low"), ("high", "high"), ("xhigh", "xhigh")):
            request = codex_request()
            request["reasoning"] = {"effort": effort, "summary": "auto"}
            body, _ = responses_to_anthropic(request)
            self.assertEqual(body["messages"][-1]["output_config"], {"effort": expected})
            self.assertEqual(body["output_config"], {"effort": "low"})
        request = codex_request()
        request["reasoning"] = {"effort": "none"}
        body, ctx = responses_to_anthropic(request)
        self.assertNotIn("thinking", body)
        self.assertNotIn("output_config", body)
        self.assertFalse(any(m["role"] == "system" for m in body["messages"]))
        self.assertEqual(ctx.thinking, "none")
        self.assertEqual(ctx.betas, ())

    def test_prompt_cache_key_marks_tools_system_and_last_two_messages(self):
        self.assertTrue(self.ctx.cache_emulation)
        self.assertEqual(self.body["tools"][-1]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(self.body["system"][-1]["cache_control"], {"type": "ephemeral"})
        messages = real(self.body["messages"])
        self.assertEqual(messages[-1]["content"][-1]["cache_control"], {"type": "ephemeral"})
        # The last real message before the newest assistant turn (previous turn's breakpoint).
        newest_assistant = max(i for i, m in enumerate(messages) if m["role"] == "assistant")
        self.assertEqual(messages[newest_assistant - 1]["content"][-1]["cache_control"], {"type": "ephemeral"})
        self.assertLessEqual(json.dumps(self.body).count("cache_control"), 4)  # Anthropic's limit
        request = codex_request()
        del request["prompt_cache_key"]
        body, ctx = responses_to_anthropic(request)
        self.assertFalse(ctx.cache_emulation)
        self.assertNotIn("cache_control", json.dumps(body))

    def test_byte_counts_of_raw_and_translated_prompt(self):
        request = codex_request()
        raw_system = request["instructions"] + "\n\n" + request["input"][0]["content"][0]["text"]
        self.assertEqual(self.ctx.raw_system_bytes, len(raw_system.encode("utf-8")))
        self.assertEqual(self.ctx.system_bytes, self.ctx.raw_system_bytes)
        raw_tools = json.dumps(request["tools"], sort_keys=True, separators=(",", ":"))
        self.assertEqual(self.ctx.raw_tools_bytes, len(raw_tools.encode("utf-8")))
        sent_tools = json.dumps(strip_cache(self.body["tools"]), sort_keys=True, separators=(",", ":"))
        self.assertEqual(self.ctx.tools_bytes, len(sent_tools.encode("utf-8")))
        record = self.ctx.record()
        for key in ("responses_raw_system_bytes", "responses_raw_tools_bytes",
                    "responses_system_bytes", "responses_tools_bytes"):
            self.assertIsInstance(record[key], int)

    def test_dropped_fields_defaults_and_passthrough(self):
        self.assertEqual(self.body["max_tokens"], 32000)
        self.assertTrue(self.body["stream"])
        self.assertEqual(self.body["model"], "claude-sonnet-5-5")
        for key in ("store", "include", "prompt_cache_key", "reasoning", "parallel_tool_calls"):
            self.assertNotIn(key, self.body)
        self.assertIn("store", self.ctx.dropped_fields)
        self.assertIn("prompt_cache_key", self.ctx.dropped_fields)
        request = codex_request()
        request["max_output_tokens"] = 512
        self.assertEqual(responses_to_anthropic(request)[0]["max_tokens"], 512)

    def test_minted_reasoning_round_trips_to_thinking_blocks(self):
        request = codex_request()
        request["input"].insert(3, {"type": "reasoning", "id": "rs_1", "summary": [],
                                    "encrypted_content": encode_reasoning([THINKING])})
        body, ctx = responses_to_anthropic(request)
        assistant = real(body["messages"])[1]["content"]
        self.assertEqual(assistant[0], THINKING)
        self.assertEqual([b["type"] for b in assistant], ["thinking", "text", "tool_use"])
        foreign = codex_request()
        foreign["input"].insert(3, {"type": "reasoning", "id": "rs_x", "summary": [],
                                    "encrypted_content": "gAAAA-openai-ciphertext"})
        _, ctx = responses_to_anthropic(foreign)
        self.assertEqual(ctx.dropped_items, ("reasoning",))

    def test_string_input_and_errors(self):
        body, _ = responses_to_anthropic({"model": "m", "input": "hi"})
        self.assertEqual(body["messages"], [{"role": "user", "content": [{"type": "text", "text": "hi"}]}])
        with self.assertRaises(ResponsesError):
            responses_to_anthropic({"input": 5})
        with self.assertRaises(ResponsesError):
            responses_to_anthropic({"input": [{"type": "message", "role": "robot", "content": "x"}]})
        with self.assertRaises(ResponsesError):
            responses_to_anthropic({"input": [], "tools": [{"type": "function", "name": "a"}],
                                    "tool_choice": {"type": "function", "name": "missing"}})


def codex_turn(turn: int) -> dict:
    """Codex's request for turn 1 or 2 of one session: turn 2 is turn 1's
    input plus the model's output items (reasoning minted by this proxy,
    a function call) and the tool output."""
    request = codex_request()
    request["input"] = request["input"][:3]  # developer, env context, task
    if turn >= 2:
        request["input"] += [
            {"type": "reasoning", "id": "rs_1", "summary": [{"type": "summary_text", "text": "Plan."}],
             "encrypted_content": encode_reasoning([THINKING])},
            {"type": "function_call", "id": "fc_1", "call_id": "toolu_1", "name": "exec_command",
             "arguments": "{\"cmd\":\"ls\"}"},
            {"type": "function_call_output", "call_id": "toolu_1", "output": "app.py\n"},
        ]
    return request


def cacheable_prefix(body: dict, upto_message: int) -> bytes:
    """What Anthropic hashes for a breakpoint: tools, system, messages[:n]."""
    prefix = {"tools": body.get("tools"), "system": body.get("system"),
              "thinking": body.get("thinking"), "output_config": body.get("output_config"),
              "messages": body["messages"][:upto_message]}
    return json.dumps(strip_cache(prefix), sort_keys=True, separators=(",", ":")).encode("utf-8")


class PrefixStability(unittest.TestCase):
    """Smoke at ddd5096d: every turn wrote a fresh cache and read 0. Two
    consecutive translated turns must share a byte-identical prefix up to the
    previous turn's breakpoint, so turn 2 reads what turn 1 wrote."""

    def setUp(self):
        self.t1, self.c1 = responses_to_anthropic(codex_turn(1))
        self.t2, self.c2 = responses_to_anthropic(codex_turn(2))

    def breakpoint_index(self, body: dict) -> int:
        """Index of the last message carrying a cache marker."""
        return max(i for i, m in enumerate(body["messages"])
                   if any("cache_control" in b for b in m.get("content") or []))

    def test_tools_and_system_are_identical_across_turns(self):
        self.assertEqual(strip_cache(self.t1["tools"]), strip_cache(self.t2["tools"]))
        self.assertEqual(strip_cache(self.t1["system"]), strip_cache(self.t2["system"]))
        self.assertEqual((self.c1.tools_sha, self.c1.system_sha), (self.c2.tools_sha, self.c2.system_sha))
        self.assertEqual(self.t1["thinking"], self.t2["thinking"])
        self.assertEqual(self.t1["output_config"], self.t2["output_config"])

    def test_turn_two_repeats_turn_one_up_to_its_breakpoint(self):
        upto = self.breakpoint_index(self.t1) + 1
        self.assertEqual(cacheable_prefix(self.t1, upto), cacheable_prefix(self.t2, upto))
        # The turn-1 breakpoint block is still marked in turn 2 (second-to-last
        # real message), so Anthropic's lookup lands on the exact entry.
        marked = [i for i, m in enumerate(self.t2["messages"])
                  if any("cache_control" in b for b in m.get("content") or [])]
        self.assertIn(upto - 1, marked)

    def test_turn_two_adds_only_after_the_prefix(self):
        upto = self.breakpoint_index(self.t1) + 1
        added = real(self.t2["messages"][upto:])
        self.assertEqual([m["role"] for m in added], ["assistant", "user"])
        self.assertEqual(added[0]["content"][0], THINKING)
        self.assertEqual(added[1]["content"][0]["tool_use_id"], "toolu_1")

    def test_translation_is_deterministic(self):
        again, _ = responses_to_anthropic(codex_turn(2))
        self.assertEqual(json.dumps(again), json.dumps(self.t2))


class UsageFixture(unittest.TestCase):
    def test_anthropic_usage_projects_to_responses_usage(self):
        fixture = usage_fixture()
        self.assertEqual(responses_usage(fixture["anthropic"]), fixture["responses"])

    def test_cache_creation_breakdown_counts_when_total_absent(self):
        usage = {"input_tokens": 1, "output_tokens": 2,
                 "cache_creation": {"ephemeral_5m_input_tokens": 3, "ephemeral_1h_input_tokens": 4}}
        self.assertEqual(responses_usage(usage)["input_tokens"], 8)
        self.assertEqual(responses_usage(usage)["cache_creation_input_tokens"], 7)


class ReplyTranslation(unittest.TestCase):
    def test_message_with_thinking_text_and_tools(self):
        ctx = ResponsesContext(custom_tools=frozenset({"apply_patch"}))
        message = {
            "id": "msg_1", "stop_reason": "tool_use",
            "content": [
                THINKING,
                {"type": "text", "text": "Running ls."},
                {"type": "tool_use", "id": "toolu_9", "name": "exec_command", "input": {"cmd": "ls"}},
                {"type": "tool_use", "id": "toolu_10", "name": "apply_patch", "input": {"input": "PATCH"}},
            ],
            "usage": usage_fixture()["anthropic"],
        }
        resp = anthropic_message_to_responses(message, "claude-sonnet-5-5", ctx)
        self.assertEqual(resp["status"], "completed")
        kinds = [item["type"] for item in resp["output"]]
        self.assertEqual(kinds, ["reasoning", "message", "function_call", "custom_tool_call"])
        self.assertEqual(decode_reasoning(resp["output"][0]["encrypted_content"]), [THINKING])
        self.assertEqual(resp["output"][0]["summary"][0]["text"], "Check the tests first.")
        self.assertEqual(resp["output"][1]["content"][0]["text"], "Running ls.")
        self.assertEqual(resp["output"][2]["call_id"], "toolu_9")
        self.assertEqual(json.loads(resp["output"][2]["arguments"]), {"cmd": "ls"})
        self.assertEqual(resp["output"][3]["input"], "PATCH")
        self.assertEqual(resp["usage"], usage_fixture()["responses"])

    def test_max_tokens_is_incomplete(self):
        resp = anthropic_message_to_responses(
            {"id": "m", "stop_reason": "max_tokens", "content": [{"type": "text", "text": "x"}]},
            "m", ResponsesContext())
        self.assertEqual(resp["status"], "incomplete")
        self.assertEqual(resp["incomplete_details"], {"reason": "max_output_tokens"})

    def test_error_shape(self):
        body = json.loads(responses_error_bytes(b'{"error":{"type":"overloaded_error","message":"busy"}}'))
        self.assertEqual(body, {"error": {"message": "busy", "type": "overloaded_error",
                                          "code": "overloaded_error"}})
        self.assertIn("error", json.loads(responses_error_bytes(b"<html>bad gateway</html>")))

    def test_envelope_only_decodes_its_own_prefix(self):
        self.assertTrue(encode_reasoning([THINKING]).startswith(REASONING_ENVELOPE))
        self.assertIsNone(decode_reasoning("gAAAA"))
        self.assertIsNone(decode_reasoning(REASONING_ENVELOPE + "!!not-base64!!"))


ANTHROPIC_STREAM = sse(
    {"type": "message_start", "message": {"id": "msg_s", "usage": {
        "input_tokens": 1200, "output_tokens": 1,
        "cache_read_input_tokens": 9000, "cache_creation_input_tokens": 500}}},
    {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "Plan."}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "sig"}},
    {"type": "content_block_stop", "index": 0},
    {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "Run"}},
    {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "ning."}},
    {"type": "content_block_stop", "index": 1},
    {"type": "content_block_start", "index": 2, "content_block": {
        "type": "tool_use", "id": "toolu_s", "name": "exec_command", "input": {}}},
    {"type": "content_block_delta", "index": 2, "delta": {"type": "input_json_delta", "partial_json": "{\"cmd\":"}},
    {"type": "content_block_delta", "index": 2, "delta": {"type": "input_json_delta", "partial_json": "\"ls\"}"}},
    {"type": "content_block_stop", "index": 2},
    {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 340}},
    {"type": "message_stop"},
)


class StreamTranslation(unittest.TestCase):
    def run_stream(self, payload: bytes, ctx=None, step=37):
        stream = ResponsesStream("claude-sonnet-5-5", ctx or ResponsesContext())
        chunks = []
        for i in range(0, len(payload), step):
            chunks.extend(stream.feed(payload[i:i + step]))
        chunks.extend(stream.finish())
        return parse_sse(chunks)

    def test_event_sequence_and_completed_response(self):
        events = self.run_stream(ANTHROPIC_STREAM)
        kinds = [e["type"] for e in events]
        self.assertEqual(kinds[:2], ["response.created", "response.in_progress"])
        self.assertEqual(kinds[-1], "response.completed")
        self.assertEqual([e["sequence_number"] for e in events], list(range(len(events))))
        self.assertIn("response.output_text.delta", kinds)
        self.assertIn("response.function_call_arguments.delta", kinds)
        done = [e["item"] for e in events if e["type"] == "response.output_item.done"]
        self.assertEqual([i["type"] for i in done], ["reasoning", "message", "function_call"])
        self.assertEqual(decode_reasoning(done[0]["encrypted_content"]),
                         [{"type": "thinking", "thinking": "Plan.", "signature": "sig"}])
        final = events[-1]["response"]
        self.assertEqual([i["type"] for i in final["output"]], ["reasoning", "message", "function_call"])
        self.assertEqual(final["output"][1]["content"][0]["text"], "Running.")
        self.assertEqual(json.loads(final["output"][2]["arguments"]), {"cmd": "ls"})
        self.assertEqual(final["usage"], usage_fixture()["responses"])
        self.assertEqual(final["id"], "resp_msg_s")

    def test_output_indexes_are_stable(self):
        events = self.run_stream(ANTHROPIC_STREAM)
        added = {e["item"]["id"]: e["output_index"] for e in events if e["type"] == "response.output_item.added"}
        done = {e["item"]["id"]: e["output_index"] for e in events if e["type"] == "response.output_item.done"}
        self.assertEqual(added, done)
        self.assertEqual(sorted(done.values()), [0, 1, 2])

    def test_max_tokens_stream_ends_incomplete(self):
        payload = sse(
            {"type": "message_start", "message": {"id": "m", "usage": {"input_tokens": 3}}},
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "abc"}},
            {"type": "content_block_stop", "index": 0},
            {"type": "message_delta", "delta": {"stop_reason": "max_tokens"}, "usage": {"output_tokens": 9}},
            {"type": "message_stop"},
        )
        events = self.run_stream(payload)
        self.assertEqual(events[-1]["type"], "response.incomplete")
        self.assertEqual(events[-1]["response"]["incomplete_details"], {"reason": "max_output_tokens"})

    def test_truncated_upstream_still_completes_and_fail_reports(self):
        cut = ANTHROPIC_STREAM[: ANTHROPIC_STREAM.index(b"message_delta")]
        events = self.run_stream(cut)
        self.assertEqual(events[-1]["type"], "response.completed")
        stream = ResponsesStream("m", ResponsesContext())
        stream.feed(ANTHROPIC_STREAM[:200])
        failed = parse_sse(stream.fail("upstream stream error: IncompleteRead"))
        self.assertEqual(failed[-1]["type"], "response.failed")
        self.assertEqual(failed[-1]["response"]["status"], "failed")
        self.assertEqual(stream.fail("again"), [])

    def test_custom_tool_streams_as_custom_tool_call(self):
        payload = sse(
            {"type": "message_start", "message": {"id": "m", "usage": {"input_tokens": 3}}},
            {"type": "content_block_start", "index": 0, "content_block": {
                "type": "tool_use", "id": "toolu_p", "name": "apply_patch", "input": {}}},
            {"type": "content_block_delta", "index": 0, "delta": {
                "type": "input_json_delta", "partial_json": "{\"input\":\"PATCH\"}"}},
            {"type": "content_block_stop", "index": 0},
            {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 2}},
            {"type": "message_stop"},
        )
        events = self.run_stream(payload, ResponsesContext(custom_tools=frozenset({"apply_patch"})))
        self.assertNotIn("response.function_call_arguments.delta", [e["type"] for e in events])
        item = events[-1]["response"]["output"][0]
        self.assertEqual(item, {"type": "custom_tool_call", "id": item["id"], "call_id": "toolu_p",
                                "name": "apply_patch", "input": "PATCH", "status": "completed"})


if __name__ == "__main__":
    unittest.main()
