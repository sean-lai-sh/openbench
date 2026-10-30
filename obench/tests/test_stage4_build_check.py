"""Stage 4 base agent (AC3): proxy-capture build check.

Loopback capture stub only; no model calls.
"""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from thesis.base_agent import build_check as B


def req(body, role=None, path="/v1/messages"):
    headers = {"content-type": "application/json"}
    if role:
        headers["X-OB-Call-Role"] = role
    return {"method": "POST", "path": path, "headers": headers, "body": json.dumps(body)}


TOOLS = [{"name": "bash", "description": "run", "input_schema": {"type": "object"}}]


class Measure(unittest.TestCase):
    def test_anthropic_string_and_blocks(self):
        a = B.measure({"system": "héllo", "tools": TOOLS})
        b = B.measure({"system": [{"type": "text", "text": "hé"}, {"type": "text", "text": "llo",
                                                                    "cache_control": {"type": "ephemeral"}}],
                       "tools": TOOLS})
        self.assertEqual(a["system_bytes"], 6)
        self.assertEqual(b["system_bytes"], 6)
        self.assertEqual((a["system_blocks"], b["system_blocks"]), (1, 2))

    def test_tool_bytes_ignore_cache_marks_and_key_order(self):
        marked = [{"input_schema": {"type": "object"}, "description": "run", "name": "bash",
                   "cache_control": {"type": "ephemeral"}}]
        self.assertEqual(B.measure({"tools": marked})["tools_bytes"], B.measure({"tools": TOOLS})["tools_bytes"])

    def test_chat_completions_system_messages(self):
        m = B.measure({"messages": [{"role": "system", "content": "abc"}, {"role": "user", "content": "x"}],
                       "tools": [{"type": "function", "function": {"name": "bash"}}], "max_tokens": 5})
        self.assertEqual((m["system_bytes"], m["tool_names"], m["sampling"]), (3, ["bash"], {"max_tokens": 5}))


class MainRequest(unittest.TestCase):
    def test_skips_side_calls_toolless_and_non_model_paths(self):
        reqs = [req({"system": "title", "tools": TOOLS}, role="side:title"),
                req({"system": "no tools"}),
                req({"tools": TOOLS}, path="/v1/models"),
                req({"system": "main", "tools": TOOLS})]
        self.assertEqual(json.loads(B.main_request(reqs)["body"])["system"], "main")

    def test_no_main_request_raises(self):
        with self.assertRaises(ValueError):
            B.main_request([req({"system": "x"})])


class Compare(unittest.TestCase):
    def m(self, s, t, names=("bash",)):
        return {"system_bytes": s, "tools_bytes": t, "tool_names": list(names), "sampling": {}}

    def test_five_percent_boundary_each_component(self):
        self.assertTrue(B.compare(self.m(105, 95), self.m(100, 100))["pass"])
        self.assertFalse(B.compare(self.m(106, 100), self.m(100, 100))["pass"])
        # combined within 5% is not enough when one component is off
        c = B.compare(self.m(120, 900), self.m(100, 920))
        self.assertTrue(c["combined"]["pass"])
        self.assertFalse(c["pass"])

    def test_tool_name_diff(self):
        c = B.compare(self.m(1, 1, ["a", "b"]), self.m(1, 1, ["b", "c"]))
        self.assertEqual(c["tool_names"]["missing_in_base"], ["c"])
        self.assertEqual(c["tool_names"]["extra_in_base"], ["a"])
        self.assertFalse(c["tool_names"]["same_order"])


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_capture_opencode_title_then_main(self):
        reqs, version = B.capture_base("opencode", "parity", "claude-test")
        roles = [B._role_header(r) for r in reqs]
        self.assertEqual(roles, ["side:title", "main"])
        main = json.loads(B.main_request(reqs)["body"])
        self.assertEqual(len(main["tools"]), 11)
        self.assertEqual(version["config_name"], "opencode")

    def test_self_compare_passes_and_dropped_tool_fails(self):
        reqs, _ = B.capture_base("pi", "parity", "claude-test")
        base = self.dir / "base.requests.jsonl"
        B.write_requests(base, reqs)
        rep = B.report(base, base, None)
        self.assertEqual(rep["verdict"], "PASS")
        body = json.loads(B.main_request(reqs)["body"])
        body["tools"] = body["tools"][:2]
        real = self.dir / "real.json"
        real.write_text(json.dumps(body))  # a bare request body is accepted too
        rep = B.report(base, real, None)
        self.assertEqual(rep["verdict"], "FAIL")
        self.assertEqual(rep["comparison"]["tool_names"]["extra_in_base"], ["edit", "write"])
        self.assertEqual(len(rep["base"]["sha256"]), 64)

    def test_cli_capture_and_compare(self):
        base = self.dir / "pi.requests.jsonl"
        out = self.dir / "report.json"
        with redirect_stdout(io.StringIO()):
            self.assertEqual(B.main(["capture", "--config", "pi", "--model", "claude-test", "--out", str(base)]), 0)
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = B.main(["compare", "--config", "pi", "--base", str(base), "--real", str(base), "--out", str(out)])
        self.assertEqual(code, 0)
        self.assertIn("AC3 build check: PASS", buf.getvalue())
        rep = json.loads(out.read_text())
        self.assertEqual(rep["version"]["config_name"], "pi")
        self.assertEqual(rep["version"]["arm"], "parity")


if __name__ == "__main__":
    unittest.main()
