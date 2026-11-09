"""Shared four-check smoke evidence (thesis/ab/smoke_evidence.py) and the
proxy's opt-in raw request capture (OBENCH_VERTEX_CAPTURE_REQUESTS)."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from obench.tests.test_vertex_proxy_harness_api import MESSAGE, STREAM, _post, _Vertex
from thesis.ab import smoke_evidence as se
from thesis.ab.vertex_anthropic_proxy import (prompt_bytes, request_capture_path, split_strip_beta, start_proxy,
                                              strip_requested_betas)

ROOT = Path(__file__).resolve().parents[2]


def capture_rows(cache_reads=(0, 9000, 9500, 9800), sent="none", system=(5000, 5000), tools=(2000, 2000),
                 roles=None, usage_extra=None):
    rows = []
    for i, read in enumerate(cache_reads, 1):
        usage = {"input_tokens": 1, "output_tokens_details": {"thinking_tokens": 0}}
        usage.update(usage_extra or {})
        rows.append({"usage": usage, "cache_read": read, "thinking_sent": sent,
                     "call_role": (roles or {}).get(i, "main"),
                     "cc_identity_stripped": {"capture": {
                         "raw_request_file": f"c.requests/{i:04d}.request.json",
                         "system_bytes": system[0], "raw_system_bytes": system[1],
                         "tools_bytes": tools[0], "raw_tools_bytes": tools[1]}}})
    return rows


REFERENCE = {"pi": ["adaptive"], "opencode": ["none"]}


class Evidence(unittest.TestCase):
    def test_all_four_pass_from_capture_records(self):
        evidence = se.smoke_evidence({"trace_requests": 4, "untraced_requests": 0}, capture_rows(), REFERENCE)
        self.assertEqual({k: v["pass"] for k, v in evidence.items()},
                         {"1_traced": True, "2_cache_read": True, "3_thinking_sent": True, "4_prompt_bytes": True})
        self.assertEqual(evidence["3_thinking_sent"]["reference_arm"], "opencode")
        self.assertEqual(evidence["3_thinking_sent"]["harness"], ["none"])
        self.assertEqual(evidence["4_prompt_bytes"]["per_call"][0]["raw_request_file"], "c.requests/0001.request.json")

    def test_failures_are_reported_per_check(self):
        evidence = se.smoke_evidence({"trace_requests": 1, "untraced_requests": 3},
                                     capture_rows(cache_reads=(0, 0, 0, 0), sent="adaptive", tools=(2200, 2000)),
                                     REFERENCE)
        self.assertFalse(evidence["1_traced"]["pass"])
        self.assertFalse(evidence["2_cache_read"]["pass"])
        self.assertEqual(evidence["3_thinking_sent"]["matches"], {"pi": True, "opencode": False})
        self.assertFalse(evidence["3_thinking_sent"]["pass"])
        self.assertEqual(evidence["4_prompt_bytes"]["per_call"][0]["tools_delta"], 0.1)
        self.assertFalse(evidence["4_prompt_bytes"]["pass"])

    def test_tool_less_side_call_counts_as_within(self):
        rows = capture_rows(cache_reads=(0, 7000), system=(300, 300), tools=(0, 0), roles={1: "side"})
        evidence = se.smoke_evidence({"trace_requests": 2, "untraced_requests": 0}, rows, REFERENCE)
        self.assertTrue(evidence["4_prompt_bytes"]["pass"])
        self.assertEqual(evidence["4_prompt_bytes"]["per_call"][0]["call_role"], "side")

    def test_strict_rule_fails_on_any_server_thinking_tokens(self):
        rows = capture_rows(usage_extra={"output_tokens_details": {"thinking_tokens": 1051}})
        check = se.smoke_evidence({"trace_requests": 4, "untraced_requests": 0}, rows, REFERENCE)["3_thinking_sent"]
        self.assertEqual(check["server_thinking_tokens_per_call"], [1051] * 4)
        self.assertEqual(check["harness"], ["none"])
        self.assertFalse(check["pass"])  # thinking_sent is none, but the server thought
        self.assertEqual(check["failing_calls"], [1, 2, 3, 4])

    def test_strict_rule_covers_side_calls_and_unreported_tokens(self):
        rows = capture_rows(roles={4: "side"})
        rows[3]["usage"]["output_tokens_details"]["thinking_tokens"] = 12  # the title call
        check = se.smoke_evidence({"trace_requests": 4, "untraced_requests": 0}, rows, REFERENCE)["3_thinking_sent"]
        self.assertFalse(check["pass"])
        self.assertEqual(check["failing_calls"], [4])
        self.assertEqual(check["per_call"][3]["call_role"], "side")
        rows = capture_rows()
        rows[1]["usage"].pop("output_tokens_details")  # no thinking-token field: can't show 0
        check = se.smoke_evidence({"trace_requests": 4, "untraced_requests": 0}, rows, REFERENCE)["3_thinking_sent"]
        self.assertEqual(check["failing_calls"], [2])

    def test_strict_rule_passes_only_on_none_and_zero_everywhere(self):
        rows = capture_rows()
        rows[2]["thinking_type"] = "between_tools"  # folded into thinking_sent=none, shown per call
        check = se.smoke_evidence({"trace_requests": 4, "untraced_requests": 0}, rows, REFERENCE)["3_thinking_sent"]
        self.assertTrue(check["pass"])
        self.assertEqual(check["per_call"][2]["thinking_type"], "between_tools")
        rows[0]["thinking_sent"] = "adaptive"
        self.assertFalse(se.smoke_evidence({"trace_requests": 4, "untraced_requests": 0}, rows,
                                           REFERENCE)["3_thinking_sent"]["pass"])
        self.assertIsNone(se.server_thinking_tokens({"input_tokens": 3}))
        self.assertEqual(se.server_thinking_tokens({"reasoning_tokens": 5, "output_tokens_details":
                                                    {"reasoning_tokens": 2}}), 7)

    def test_fa92664b_smoke_shape_still_fails_cache_and_thinking(self):
        """The fa92664b cell: cache reads [0, 0, title 0], thinking [2565, 139, 0].

        Two main calls cannot show the later-read region-split signature.
        The checks stay strict: call 2 must read cache, and every call must
        have zero server thinking tokens.
        """
        rows = [
            {"usage": {"output_tokens_details": {"thinking_tokens": 2565}},
             "cache_read": 0, "cache_write": 17159, "thinking_sent": "none", "call_role": "main"},
            {"usage": {"output_tokens_details": {"thinking_tokens": 139}},
             "cache_read": 0, "cache_write": 4000, "thinking_sent": "none", "call_role": "main"},
            {"usage": {"output_tokens_details": {"thinking_tokens": 0}},
             "cache_read": 0, "cache_write": 0, "thinking_sent": "none", "call_role": "side",
             "call_role_reason": "heuristic:title-schema"},
        ]
        evidence = se.smoke_evidence({"trace_requests": 3, "untraced_requests": 0}, rows, REFERENCE)
        self.assertEqual(evidence["2_cache_read"]["per_call"], [0, 0])
        self.assertEqual(evidence["2_cache_read"]["calls"][2]["call_role"], "side")
        self.assertFalse(evidence["2_cache_read"]["pass"])
        self.assertFalse(evidence["2_cache_read"]["misses"][0]["region_split_signature"])
        self.assertEqual(evidence["3_thinking_sent"]["server_thinking_tokens_per_call"], [2565, 139, 0])
        self.assertEqual(evidence["3_thinking_sent"]["failing_calls"], [1, 2])
        self.assertFalse(evidence["3_thinking_sent"]["pass"])

    def test_hermes_smoke_ledger_check2_is_main_only_with_the_region_split_signature(self):
        # The four calls of the first Hermes VM cell (df4934f90f6f8d26).
        rows = [
            {"usage": {}, "cache_read": 0, "cache_write": 17159, "call_role": "main"},
            {"usage": {}, "cache_read": 0, "cache_write": 17977, "call_role": "main"},
            {"usage": {}, "cache_read": 17159, "cache_write": 1078, "call_role": "main"},
            {"usage": {}, "cache_read": 0, "cache_write": 0, "call_role": "side",
             "call_role_reason": "heuristic:title-schema"},
        ]
        check = se.smoke_evidence({"trace_requests": 4, "untraced_requests": 0}, rows, REFERENCE,
                                  reference_cache={"opencode": {"cells": 90, "call2_miss": 28}})["2_cache_read"]
        self.assertEqual(check["per_call"], [0, 0, 17159])  # the title call is not in the rule
        self.assertEqual(check["side_calls_excluded"], 1)
        self.assertEqual([c["call_role"] for c in check["calls"]], ["main", "main", "main", "side"])
        self.assertEqual(check["misses"], [{
            "main_call": 2, "cache_write": 17977, "region_split_signature": True,
            "later_read_of_earlier_prefix": {"main_call": 3, "read": 17159, "matches_prefix_of_main_call": 1}}])
        self.assertFalse(check["pass"])
        self.assertEqual(check["reference_call2_miss"]["opencode"]["call2_miss"], 28)

    def test_side_call_without_cache_does_not_fail_check2(self):
        rows = capture_rows(cache_reads=(0, 9000, 9500, 0), roles={4: "side"})
        check = se.smoke_evidence({"trace_requests": 4, "untraced_requests": 0}, rows, REFERENCE)["2_cache_read"]
        self.assertTrue(check["pass"])
        self.assertEqual(check["misses"], [])

    def test_plain_miss_has_no_region_split_signature(self):
        rows = [{"usage": {}, "cache_read": 0, "cache_write": 500},
                {"usage": {}, "cache_read": 0, "cache_write": 900},
                {"usage": {}, "cache_read": 900, "cache_write": 40}]
        misses = se.cache_misses(rows)
        self.assertEqual(misses[0]["main_call"], 2)
        self.assertFalse(misses[0]["region_split_signature"])

    def test_opencode_reference_also_misses_call2(self):
        rate = se.reference_call2_miss(ROOT, "claude-sonnet-5-5")
        self.assertGreater(rate["opencode"]["cells"], 0)
        self.assertGreater(rate["opencode"]["call2_miss"], 0)

    def test_reference_comes_from_the_196_ledgers(self):
        self.assertEqual(se.reference_thinking(ROOT, "claude-sonnet-5-5"), REFERENCE)

    def test_responses_records_still_work(self):
        rows = [{"usage": {"input_tokens": 1}, "cache_read": 0, "thinking_sent": "none",
                 "cc_identity_stripped": {"responses": {
                     "responses_raw_request_file": "c.responses/0001.request.json",
                     "responses_system_bytes": 10, "responses_raw_system_bytes": 10,
                     "responses_tools_bytes": 10, "responses_raw_tools_bytes": 10}}}]
        evidence = se.smoke_evidence({"trace_requests": 1, "untraced_requests": 0}, rows, REFERENCE)
        self.assertTrue(evidence["4_prompt_bytes"]["pass"])


class RequestCapture(unittest.TestCase):
    def setUp(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Vertex)
        self.httpd.seen, self.httpd.queue = [], []
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
        self.body = {"model": "claude-sonnet-5-5", "max_tokens": 32000,
                     "system": [{"type": "text", "text": "You are Hermes. " * 20,
                                 "cache_control": {"type": "ephemeral"}}],
                     "tools": [{"name": "terminal", "description": "run", "input_schema": {"type": "object"}}],
                     "messages": [{"role": "user", "content": "hi"}]}

    def row(self, cell):
        return [json.loads(l) for l in (self.ledger / f"{cell}.jsonl").read_text().splitlines() if l.strip()][-1]

    def test_messages_bodies_are_captured_raw_with_byte_counts(self):
        raw = json.dumps(self.body).encode("utf-8")
        with patch.dict(os.environ, {"OBENCH_VERTEX_CAPTURE_REQUESTS": "1"}):
            _post(f"{self.proxy.base_url}/c/cell-cap/v1/messages", raw)
        self.assertEqual(request_capture_path(self.ledger, "cell-cap", 1).read_bytes(), raw)
        capture = self.row("cell-cap")["cc_identity_stripped"]["capture"]
        system, tools = prompt_bytes(self.body)
        self.assertEqual(capture["raw_request_file"], "cell-cap.requests/0001.request.json")
        self.assertEqual((capture["raw_system_bytes"], capture["raw_tools_bytes"]), (system, tools))
        self.assertEqual((capture["system_bytes"], capture["tools_bytes"]), (system, tools))

    def test_capture_is_off_by_default(self):
        with patch.dict(os.environ, {"OBENCH_VERTEX_CAPTURE_REQUESTS": ""}):
            _post(f"{self.proxy.base_url}/c/cell-off/v1/messages", self.body)
        self.assertFalse(request_capture_path(self.ledger, "cell-off", 1).exists())
        self.assertNotIn("capture", self.row("cell-off").get("cc_identity_stripped") or {})


HERMES_BETAS = "interleaved-thinking-2025-05-14,fine-grained-tool-streaming-2025-05-14"


class BetaStrip(RequestCapture):
    """AD1-hermes-beta: the Hermes cell URL's strip-beta segment keeps
    interleaved-thinking off the upstream request and records it per call."""

    def hermes_url(self, cell):
        from obench.adapters.hermes_harness import cell_proxy_base
        return cell_proxy_base(self.proxy.base_url, cell) + "/v1/messages"

    def test_interleaved_thinking_is_not_sent_upstream(self):
        status, _ = _post(self.hermes_url("cell-b"), self.body, {"anthropic-beta": HERMES_BETAS})
        self.assertEqual(status, 200)
        upstream = self.httpd.seen[-1]
        self.assertEqual(upstream["beta"], "fine-grained-tool-streaming-2025-05-14")
        self.assertNotIn("interleaved-thinking", upstream["beta"])
        self.assertNotIn("strip-beta", upstream["path"])  # the segment never reaches Vertex
        self.assertTrue(upstream["path"].endswith(":rawPredict") or upstream["path"].endswith(":streamRawPredict"))
        forwarded = json.loads(upstream["body"])
        # The strip is a header edit. It must not invent a thinking disable.
        self.assertNotIn("thinking", forwarded)
        self.assertEqual(forwarded["system"][0]["cache_control"], {"type": "ephemeral"})
        row = self.row("cell-b")
        self.assertEqual(row["beta_stripped"], {"requested": ["interleaved-thinking-2025-05-14"],
                                                "removed": ["interleaved-thinking-2025-05-14"]})
        self.assertEqual(row["cc_identity_stripped"]["beta_stripped"], row["beta_stripped"])
        self.assertFalse(row["cc_identity_stripped"]["stripped"])  # not a Claude Code identity strip

    def test_header_with_only_the_stripped_beta_is_not_forwarded(self):
        _post(self.hermes_url("cell-o"), self.body, {"anthropic-beta": "interleaved-thinking-2025-05-14"})
        self.assertIsNone(self.httpd.seen[-1]["beta"])
        self.assertEqual(self.row("cell-o")["beta_stripped"]["removed"], ["interleaved-thinking-2025-05-14"])

    def test_no_header_records_nothing_removed(self):
        _post(self.hermes_url("cell-n"), self.body)
        self.assertIsNone(self.httpd.seen[-1]["beta"])
        self.assertEqual(self.row("cell-n")["beta_stripped"]["removed"], [])

    def test_other_routes_forward_the_beta_unchanged(self):
        _post(f"{self.proxy.base_url}/c/cell-p/v1/messages", self.body, {"anthropic-beta": HERMES_BETAS})
        self.assertEqual(self.httpd.seen[-1]["beta"], HERMES_BETAS)
        self.assertNotIn("beta_stripped", self.row("cell-p"))

    def test_raw_thinking_type_is_recorded_beside_thinking_sent(self):
        body = dict(self.body, thinking={"type": "between_tools"})
        _post(self.hermes_url("cell-t"), body)
        row = self.row("cell-t")
        self.assertEqual((row["thinking_sent"], row["thinking_type"]), ("none", "between_tools"))
        _post(self.hermes_url("cell-u"), self.body)
        self.assertNotIn("thinking_type", self.row("cell-u"))

    def test_segment_parsing(self):
        self.assertEqual(split_strip_beta("/strip-beta/a,b/v1/messages?beta=true"),
                         ("/v1/messages?beta=true", ["a", "b"]))
        self.assertEqual(split_strip_beta("/v1/messages"), ("/v1/messages", []))
        self.assertEqual(strip_requested_betas(HERMES_BETAS, ["interleaved-thinking-2025-05-14"]),
                         ("fine-grained-tool-streaming-2025-05-14", ["interleaved-thinking-2025-05-14"]))
        self.assertEqual(strip_requested_betas(None, ["x"]), (None, []))


if __name__ == "__main__":
    unittest.main()
