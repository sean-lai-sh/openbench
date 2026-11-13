"""SEA-104: the OpenCode pin and the per-step trace (obench/reflection).

Fixtures are synthetic but follow the event shapes of OpenCode at the pin
(``packages/opencode/src/cli/cmd/run.ts``, ``session/message-v2.ts``). No
model calls, no network, no OpenCode binary.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from obench.reflection import opencode as oc
from obench.reflection import trace as tr

DOC = Path(tr.__file__).with_name("TRACE_SCHEMA.md")
SES = "ses_test"


def ev(kind, ts, msg, **part):
    part_type = {"step_start": "step-start", "step_finish": "step-finish", "tool_use": "tool"}.get(kind, kind)
    return {"type": kind, "timestamp": ts, "sessionID": SES,
            "part": {"id": f"prt_{ts}", "sessionID": SES, "messageID": msg, "type": part_type, **part}}


def finish(ts, msg, reason, cost, out, reasoning=0):
    return ev("step_finish", ts, msg, reason=reason, cost=cost,
              tokens={"total": out, "input": 3, "output": out, "reasoning": reasoning,
                      "cache": {"read": 0, "write": 0}})


def opencode_stream():
    """Three steps: a completed tool call, an errored one (absent from the
    stream at the pin), then a final answer. Steps 1 and 3 carry thinking."""
    return [
        ev("step_start", 1000, "msg_1"),
        ev("reasoning", 1100, "msg_1", text="Look at the files first.", time={"start": 1001, "end": 1100}),
        ev("tool_use", 1200, "msg_1", callID="toolu_1", tool="bash",
           state={"status": "completed", "input": {"command": "ls"}, "output": "main.rs\n",
                  "title": "ls", "metadata": {}, "time": {"start": 1150, "end": 1200}}),
        finish(1201, "msg_1", "tool-calls", 0.01, 40),
        ev("step_start", 2000, "msg_2"),
        finish(2500, "msg_2", "tool-calls", 0.02, 60),
        ev("step_start", 3000, "msg_3"),
        ev("reasoning", 3100, "msg_3", text="The build fails; fix the import.", time={"start": 3001, "end": 3100}),
        ev("text", 3400, "msg_3", text="Fixed the import; it builds now.", time={"start": 3300, "end": 3400}),
        finish(3401, "msg_3", "stop", 0.03, 90),
    ]


THINKING = {"type": "adaptive", "display": "summarized"}


def anthropic_usage(thinking, cache_read=0, cache_write=500):
    return {"input_tokens": 3, "output_tokens": 100 + thinking, "cache_read_input_tokens": cache_read,
            "cache_creation_input_tokens": cache_write, "output_tokens_details": {"thinking_tokens": thinking}}


def wire(index, body, usage, role="main", wire_kind="anthropic"):
    return {"schema": tr.WIRE_SCHEMA, "call_index": index, "ts": f"t{index}", "provider_wire": wire_kind,
            "call_role": role, "requested_model": "claude-opus-5-5", "upstream_model": "claude-opus-5-5",
            "request": body, "response_usage": usage, "status": 200}


def anthropic_wires():
    sys_ = [{"type": "text", "text": "You are a coding agent."}]
    user = {"role": "user", "content": "Make it build."}
    a1 = {"role": "assistant", "content": [{"type": "tool_use", "id": "toolu_1", "name": "bash",
                                             "input": {"command": "ls"}}]}
    r1 = {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "main.rs\n"}]}
    a2 = {"role": "assistant", "content": [{"type": "tool_use", "id": "toolu_2", "name": "bash",
                                             "input": {"command": "cargo build"}}]}
    r2 = {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_2", "is_error": True,
                                       "content": [{"type": "text", "text": "error[E0432]: unresolved import"}]}]}
    body = lambda msgs: {"model": "claude-opus-5-5", "max_tokens": 32000, "thinking": THINKING,
                         "system": sys_, "messages": msgs}
    return [
        wire(1, body([user]), anthropic_usage(120, cache_write=900)),
        wire(2, {"model": "claude-opus-5-5", "max_tokens": 512, "thinking": {"type": "disabled"},
                 "messages": [user]}, {"input_tokens": 50, "output_tokens": 9}, role="side"),
        wire(3, body([user, a1, r1]), anthropic_usage(0, cache_read=900)),
        wire(4, body([user, a1, r1, a2, r2]), anthropic_usage(233, cache_read=1100)),
    ]


class MultiStep(unittest.TestCase):
    def setUp(self):
        self.records = tr.build_trace(opencode_stream(), anthropic_wires(), run={"task": "t", "trial": 1})

    def test_every_step_is_written_in_order(self):
        self.assertEqual([r["step"] for r in self.records], [1, 2, 3])
        self.assertEqual([r["message_id"] for r in self.records], ["msg_1", "msg_2", "msg_3"])
        self.assertEqual([r["finish_reason"] for r in self.records], ["tool-calls", "tool-calls", "stop"])
        self.assertEqual([r["request"]["call_index"] for r in self.records], [1, 3, 4])  # side call 2 skipped
        self.assertEqual(self.records[0]["started_at"], "1970-01-01T00:00:01.000+00:00")
        for r in self.records:
            self.assertEqual(r["schema"], "openbench.reflection.step/v1")
            self.assertEqual(r["harness"]["sha"], oc.load_pin()["sha"])
            self.assertEqual(r["model"], {"requested": "claude-opus-5-5", "served": "claude-opus-5-5",
                                          "wire": "anthropic"})
            self.assertEqual(r["run"], {"task": "t", "trial": 1})

    def test_tool_calls_include_the_errored_call_recovered_from_the_next_request(self):
        first, second, third = (r["tool_calls"] for r in self.records)
        self.assertEqual(first, [{"call_id": "toolu_1", "name": "bash", "arguments": {"command": "ls"},
                                  "result": "main.rs\n", "status": "completed", "source": "opencode.tool_use"}])
        self.assertEqual(second, [{"call_id": "toolu_2", "name": "bash", "arguments": {"command": "cargo build"},
                                   "result": "error[E0432]: unresolved import", "status": "error",
                                   "source": "next_request"}])
        self.assertEqual(third, [])

    def test_text_and_thinking_per_step(self):
        self.assertEqual(self.records[2]["assistant_text"], "Fixed the import; it builds now.")
        t1, t2, t3 = (r["thinking"] for r in self.records)
        self.assertEqual((t1["kind"], t1["text"]), ("summary", "Look at the files first."))
        self.assertEqual((t2["kind"], t2["text"], t2["parts"]), ("none", "", 0))
        self.assertEqual((t3["kind"], t3["source"]), ("summary", "opencode.reasoning"))

    def test_thinking_tokens_come_from_response_usage_not_opencode(self):
        u1, u2, u3 = (r["usage"] for r in self.records)
        self.assertEqual([u["thinking_tokens"] for u in (u1, u2, u3)], [120, 0, 233])
        self.assertEqual(u3["thinking_tokens_field"], "output_tokens_details.thinking_tokens")
        self.assertEqual(self.records[2]["opencode_tokens"]["reasoning"], 0)  # OpenCode's own split disagrees
        self.assertEqual(u3["source"], "response.usage")
        self.assertEqual(u3["raw"], anthropic_usage(233, cache_read=1100))
        self.assertEqual((u1["cache_read_tokens"], u1["cache_write_tokens"]), (0, 900))
        self.assertEqual((u3["cache_read_tokens"], u3["cache_write_tokens"]), (1100, 500))

    def test_explicit_thinking_setting_is_on_every_request(self):
        for r in self.records:
            self.assertEqual(r["request"]["thinking_setting"],
                             {"explicit": True, "field": "thinking", "value": THINKING})
            self.assertEqual(r["request"]["payload"]["thinking"], THINKING)

    def test_cost_from_opencode_or_the_runner_hook(self):
        self.assertEqual([r["cost"] for r in self.records],
                         [{"usd": c, "source": "opencode.step_finish"} for c in (0.01, 0.02, 0.03)])
        priced = tr.build_trace(opencode_stream(), anthropic_wires(),
                                cost_fn=lambda rec: (rec["usage"]["input_tokens"] * 1e-6, "ledger"))
        self.assertEqual(priced[0]["cost"], {"usd": 3e-06, "source": "ledger"})

    def test_written_jsonl_round_trips(self):
        with tempfile.TemporaryDirectory() as d:
            path = tr.write_trace(Path(d) / "trace.jsonl", self.records)
            lines = path.read_text().splitlines()
        self.assertEqual([json.loads(line) for line in lines], self.records)
        self.assertFalse(Path(d, "trace.jsonl.tmp").exists())


class ThinkingShapes(unittest.TestCase):
    def one_step(self, wire_kind, body, usage, reasoning=None):
        events = [ev("step_start", 1, "m")]
        if reasoning is not None:
            events.append(ev("reasoning", 2, "m", text=reasoning, time={"start": 1, "end": 2}))
        events.append(finish(3, "m", "stop", 0.0, 10))
        return tr.build_trace(events, [wire(1, body, usage, wire_kind=wire_kind)])[0]

    def test_carbon_style_summary_only_thinking_is_accepted(self):
        body = {"contents": [{"role": "user", "parts": [{"text": "go"}]}],
                "generationConfig": {"thinkingConfig": {"thinkingLevel": "high", "includeThoughts": True}}}
        usage = {"promptTokenCount": 40, "candidatesTokenCount": 12, "thoughtsTokenCount": 512,
                 "cachedContentTokenCount": 0, "totalTokenCount": 564}
        rec = self.one_step("gemini", body, usage, reasoning="**Planning the fix** I'll check the build.")
        self.assertEqual(rec["thinking"]["kind"], "summary")
        self.assertIn("rolling thought summaries", rec["thinking"]["rule"])
        self.assertEqual(rec["usage"]["thinking_tokens"], 512)
        self.assertEqual(rec["request"]["thinking_setting"]["field"], "generationConfig.thinkingConfig")
        # Summary-only with nothing returned this step: thinking tokens but no text.
        rec = self.one_step("gemini", body, dict(usage, thoughtsTokenCount=300))
        self.assertEqual((rec["thinking"]["kind"], rec["thinking"]["text"]), ("omitted", ""))
        # Gemini omits candidatesTokenCount when nothing visible was generated.
        rec = self.one_step("gemini", body, {"promptTokenCount": 40, "thoughtsTokenCount": 64})
        self.assertEqual(rec["usage"]["output_tokens"], 0)

    def test_openai_chat_reasoning_is_full(self):
        body = {"model": "gpt-oss-120b", "reasoning_effort": "high", "messages": [{"role": "user", "content": "go"}]}
        usage = {"prompt_tokens": 20, "completion_tokens": 300, "prompt_tokens_details": {"cached_tokens": 8},
                 "completion_tokens_details": {"reasoning_tokens": 250}}
        rec = self.one_step("openai_chat", body, usage, reasoning="raw chain of thought")
        self.assertEqual(rec["thinking"]["kind"], "full")
        self.assertEqual((rec["usage"]["thinking_tokens"], rec["usage"]["cache_read_tokens"],
                          rec["usage"]["cache_write_tokens"]), (250, 8, None))
        self.assertEqual(rec["request"]["thinking_setting"], {"explicit": True, "field": "reasoning_effort",
                                                              "value": "high"})

    def test_redacted_and_explicitly_disabled(self):
        events = [ev("step_start", 1, "m"),
                  ev("reasoning", 2, "m", text="", metadata={"anthropic": {"redactedData": "xx"}},
                     time={"start": 1, "end": 2}),
                  finish(3, "m", "stop", 0.0, 10)]
        body = {"thinking": {"type": "enabled", "budget_tokens": 2048}, "messages": []}
        rec = tr.build_trace(events, [wire(1, body, anthropic_usage(40))])[0]
        self.assertEqual(rec["thinking"]["kind"], "redacted")
        off = {"thinking": {"type": "disabled"}, "messages": []}
        rec = self.one_step("anthropic", off, anthropic_usage(0))
        self.assertTrue(rec["request"]["thinking_setting"]["explicit"])  # disabled is explicit, not unset
        self.assertEqual(rec["thinking"]["kind"], "none")


class GeminiToolMatching(unittest.TestCase):
    """Repeated or parallel calls to one tool each get their own response."""

    def body(self, calls, responses):
        return {"contents": [{"role": "user", "parts": [{"text": "go"}]},
                             {"role": "model", "parts": [{"functionCall": c} for c in calls]},
                             {"role": "user", "parts": [{"functionResponse": r} for r in responses]}]}

    def results(self, calls, responses):
        return [(c["call_id"], c["result"]) for c in tr.tool_calls_from_next_request("gemini", self.body(calls, responses))]

    def test_matched_by_call_id_even_out_of_order(self):
        calls = [{"id": "c1", "name": "bash", "args": {"command": "ls"}},
                 {"id": "c2", "name": "bash", "args": {"command": "pwd"}}]
        responses = [{"id": "c2", "name": "bash", "response": {"output": "/app"}},
                     {"id": "c1", "name": "bash", "response": {"output": "main.rs"}}]
        self.assertEqual(self.results(calls, responses),
                         [("c1", {"output": "main.rs"}), ("c2", {"output": "/app"})])

    def test_without_ids_falls_back_to_occurrence_order_per_name(self):
        calls = [{"name": "bash", "args": {"command": "ls"}}, {"name": "read", "args": {"path": "a"}},
                 {"name": "bash", "args": {"command": "pwd"}}]
        responses = [{"name": "bash", "response": {"output": "main.rs"}}, {"name": "read", "response": {"text": "A"}},
                     {"name": "bash", "response": {"output": "/app"}}]
        self.assertEqual([r for _, r in self.results(calls, responses)],
                         [{"output": "main.rs"}, {"text": "A"}, {"output": "/app"}])

    def test_missing_response_is_none_not_another_calls_result(self):
        calls = [{"id": "c1", "name": "bash", "args": {}}, {"id": "c2", "name": "bash", "args": {}}]
        responses = [{"id": "c1", "name": "bash", "response": {"output": "one"}}]
        self.assertEqual(self.results(calls, responses), [("c1", {"output": "one"}), ("c2", None)])


class Packaging(unittest.TestCase):
    def test_pin_and_schema_are_package_data(self):
        """load_pin() reads opencode_pin.json at run time, so a wheel must ship it."""
        import fnmatch
        import tomllib

        root = Path(oc.__file__).resolve().parents[2]
        globs = tomllib.loads((root / "pyproject.toml").read_text())["tool"]["setuptools"]["package-data"]["obench"]
        for rel in ("reflection/opencode_pin.json", "reflection/TRACE_SCHEMA.md"):
            self.assertTrue(any(fnmatch.fnmatch(rel, g) for g in globs), rel)


class Failures(unittest.TestCase):
    def assert_code(self, code, events, wires, step=None):
        with self.assertRaises(tr.TraceError) as caught:
            tr.build_trace(events, wires)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(caught.exception.step, step)

    def test_missing_usage_fails_with_its_step(self):
        wires = anthropic_wires()
        wires[2]["response_usage"] = None
        self.assert_code("usage_missing", opencode_stream(), wires, step=2)

    def test_malformed_usage_fails_in_a_defined_way(self):
        for mutate in (lambda u: "not-an-object", lambda u: {k: v for k, v in u.items() if k != "input_tokens"},
                       lambda u: dict(u, output_tokens="410"), lambda u: dict(u, cache_read_input_tokens=-1),
                       lambda u: dict(u, output_tokens_details={"thinking_tokens": 1.5})):
            wires = anthropic_wires()
            wires[3]["response_usage"] = mutate(wires[3]["response_usage"])
            with self.subTest(usage=wires[3]["response_usage"]):
                self.assert_code("usage_malformed", opencode_stream(), wires, step=3)

    def test_unset_thinking_is_refused(self):
        wires = anthropic_wires()
        del wires[0]["request"]["thinking"]
        self.assert_code("thinking_unset", opencode_stream(), wires, step=1)
        rec = tr.build_trace(opencode_stream(), wires, require_explicit_thinking=False)
        self.assertFalse(rec[0]["request"]["thinking_setting"]["explicit"])

    def test_step_and_call_counts_must_pair(self):
        self.assert_code("step_call_mismatch", opencode_stream(), anthropic_wires()[:3])

    def test_missing_request_and_bad_wire(self):
        wires = anthropic_wires()
        wires[0]["request"] = None
        self.assert_code("request_missing", opencode_stream(), wires, step=1)
        wires = anthropic_wires()
        wires[1]["schema"] = "other"
        self.assert_code("wire_malformed", opencode_stream(), wires)

    def test_malformed_events(self):
        with self.assertRaises(tr.TraceError) as caught:
            tr.parse_events(['{"no_type": 1}'])
        self.assertEqual(caught.exception.code, "events_malformed")
        self.assert_code("events_malformed", [ev("text", 1, "m", text="x")], [])

    def test_transcript_headers_and_logs_are_skipped(self):
        lines = ["# transcript header", "", "INFO plain log line",
                 *(json.dumps(e) for e in opencode_stream())]
        self.assertEqual(tr.parse_events(lines), opencode_stream())

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            events, wires, out = Path(d, "events.txt"), Path(d, "wire.jsonl"), Path(d, "trace.jsonl")
            events.write_text("\n".join(json.dumps(e) for e in opencode_stream()))
            good = anthropic_wires()
            wires.write_text("\n".join(json.dumps(w) for w in good))
            self.assertEqual(tr.main(["--events", str(events), "--wire", str(wires), "--out", str(out)]), 0)
            self.assertEqual(len(out.read_text().splitlines()), 3)
            good[0]["response_usage"] = None
            wires.write_text("\n".join(json.dumps(w) for w in good))
            out.unlink()
            self.assertEqual(tr.main(["--events", str(events), "--wire", str(wires), "--out", str(out)]), 2)
            self.assertFalse(out.exists())  # a failed run writes nothing


class ProxyLedger(unittest.TestCase):
    def test_wire_records_from_the_vertex_proxy_ledger_and_capture(self):
        with tempfile.TemporaryDirectory() as d:
            body = {"thinking": THINKING, "messages": [{"role": "user", "content": "go"}]}
            Path(d, "cell.requests").mkdir()
            Path(d, "cell.requests", "0001.request.json").write_text(json.dumps(body))
            rows = [{"record_type": "request", "usage": anthropic_usage(7), "upstream_model": "claude-opus-5-5",
                     "requested_model": "claude-opus-5-5", "call_role": "main", "status": 200,
                     "cc_identity_stripped": {"capture": {"raw_request_file": "cell.requests/0001.request.json"}}},
                    {"record_type": "request", "usage": anthropic_usage(0), "call_role": "main"}]
            wires = tr.wire_records_from_proxy_ledger(rows, Path(d))
        self.assertEqual(wires[0]["request"], body)
        self.assertEqual((wires[0]["provider_wire"], wires[0]["upstream_model"]), ("anthropic", "claude-opus-5-5"))
        self.assertIsNone(wires[1]["request"])  # no capture -> build_trace fails with request_missing


class Pin(unittest.TestCase):
    def test_pin_is_recorded_and_reproducible(self):
        pin = oc.load_pin()
        self.assertRegex(pin["sha"], r"^[0-9a-f]{40}$")
        self.assertEqual(pin["package_version"], "1.1.61")
        self.assertIn("build_opencode", pin["install_source"])
        readme = Path(oc.__file__).with_name("README.md").read_text()
        self.assertIn(f"python3 -m thesis.ab.build_opencode {pin['sha']}", readme)
        self.assertEqual(oc.pinned_binary(Path("/c"), pin), Path("/c/bin") / pin["sha"] / "opencode")

    def test_run_command_streams_thinking(self):
        cmd = oc.run_command(Path("/c/bin/x/opencode"), "do it", "vertex/claude-opus-5-5", variant="high")
        self.assertEqual(cmd, ["/c/bin/x/opencode", "run", "--format", "json", "--thinking",
                               "--model", "vertex/claude-opus-5-5", "--variant", "high", "do it"])

    def test_verify_binary_checks_location_stamp_and_records_version(self):
        pin = oc.load_pin()
        ok = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "openbench\n", "")
        with tempfile.TemporaryDirectory() as d:
            binary = Path(d, "bin", pin["sha"], "opencode")
            binary.parent.mkdir(parents=True)
            binary.write_text("")
            with self.assertRaisesRegex(oc.PinError, "build-stamp"):
                oc.verify_binary(binary, runner=ok)
            Path(binary.parent, "build-stamp.json").write_text('{"kind": "compile"}')
            got = oc.verify_binary(binary, runner=ok)
            self.assertEqual((got["sha"], got["reported_version"], got["build_stamp"]),
                             (pin["sha"], "openbench", {"kind": "compile"}))
            other = Path(d, "bin", "0" * 40, "opencode")
            other.parent.mkdir(parents=True)
            other.write_text("")
            with self.assertRaisesRegex(oc.PinError, "not under"):
                oc.verify_binary(other, runner=ok)


class SchemaDoc(unittest.TestCase):
    """TRACE_SCHEMA.md matches the writer: every documented field is written
    and every written field is documented."""

    def documented(self, heading):
        text = DOC.read_text()
        section = text.split(heading, 1)[1].split("\n## ", 1)[0]
        return {m.group(1) for m in re.finditer(r"^\| `([a-z_.\[\]]+)` \|", section, re.M)}

    def written(self, record, prefix=""):
        keys = set()
        for key, value in record.items():
            name = f"{prefix}{key}"
            if isinstance(value, dict) and key in ("model", "request", "thinking", "usage", "cost") and not prefix:
                keys |= {f"{name}.{k}" for k in value if not (key == "request" and k == "thinking_setting")}
                if key == "request":
                    keys.add("request.thinking_setting")
            elif key == "tool_calls":
                keys.add("tool_calls[]")
            else:
                keys.add(name)
        return keys

    def test_step_fields_match_the_doc(self):
        record = tr.build_trace(opencode_stream(), anthropic_wires())[0]
        self.assertEqual(self.documented("## Step record"), self.written(record))

    def test_wire_fields_match_the_doc(self):
        documented = self.documented("## Wire record")
        section = DOC.read_text().split("## Wire record", 1)[1].split("\n## ", 1)[0]
        required = {m.group(1) for m in re.finditer(r"^\| `([a-z_]+)` \| [^|]+ \| yes \|", section, re.M)}
        written = set(anthropic_wires()[0])
        self.assertLessEqual(required, written)
        self.assertLessEqual(written, documented)

    def test_error_codes_and_kinds_match_the_doc(self):
        text = DOC.read_text()
        for code in tr.ERROR_CODES:
            self.assertIn(f"| `{code}` |", text)
        for kind in tr.THINKING_KINDS:
            self.assertIn(f"`{kind}`", text)

    def test_doc_example_parses(self):
        example = DOC.read_text().split("```json", 1)[1].split("```", 1)[0]
        record = json.loads(example)
        self.assertEqual(record["schema"], tr.TRACE_SCHEMA)
        self.assertEqual(self.written(record), self.written(tr.build_trace(opencode_stream(), anthropic_wires())[0]))


if __name__ == "__main__":
    unittest.main()
