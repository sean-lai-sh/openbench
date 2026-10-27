import json
import os
import tempfile
import unittest

from obench.provider_embedded import embedded_version, scan
from thesis.ab.step8_gate import evaluate, judge
from thesis.ab.step8_request_diff import _norm, compare_requests

BUN = (b"\x00// ../../node_modules/.bun/@ai-sdk+anthropic@2.0.58+d6123d32214422cb/"
       b"node_modules/@ai-sdk/anthropic/dist/index.mjs\nvar VERSION5 = \"2.0.58\",\x00")


class ScanTest(unittest.TestCase):
    def test_bun_layout_path(self):
        self.assertEqual(scan(b"junk" + BUN + b"junk"), "2.0.58")

    def test_flat_layout_uses_version_var(self):
        data = b"// node_modules/@ai-sdk/anthropic/dist/index.mjs\nimport x;\nvar VERSION3 = \"1.2.12\", a;"
        self.assertEqual(scan(data), "1.2.12")

    def test_not_bundled(self):
        self.assertEqual(scan(b'case "@ai-sdk/anthropic": var VERSION7 = "2.0.52"'), "")

    def test_two_copies_is_ambiguous(self):
        other = BUN.replace(b"2.0.58", b"2.0.60")
        self.assertEqual(scan(BUN + other), "")

    def test_file(self):
        with tempfile.NamedTemporaryFile(delete=False) as fh:
            fh.write(BUN)
        try:
            self.assertEqual(embedded_version(fh.name), "2.0.58")
        finally:
            os.unlink(fh.name)
        self.assertEqual(embedded_version("/nonexistent/opencode"), "")


class GateTest(unittest.TestCase):
    def test_embedded_matching_pin_is_ok(self):
        ok, why = judge({"probe_method": "embedded", "provider_loaded_version": "2.0.58"}, "2.0.58")
        self.assertTrue(ok, why)

    def test_embedded_other_version_is_mismatch(self):
        ok, why = judge({"probe_method": "embedded", "provider_loaded_version": "2.0.57"}, "2.0.58")
        self.assertFalse(ok)
        self.assertIn("embedded loaded 2.0.57 != pin 2.0.58", why)

    def test_no_probe_is_unproven(self):
        self.assertFalse(judge({"provider_loaded_version": "2.0.58"}, "2.0.58")[0])
        self.assertFalse(judge({"probe_method": "strace"}, "2.0.58")[0])

    def test_evaluate_counts_bundled_side_ok(self):
        with tempfile.TemporaryDirectory() as d:
            sides = {}
            for i in range(11):
                for side, method in (("without", "strace"), ("with", "embedded" if i == 0 else "strace")):
                    pr = str(100 + i)
                    sides.setdefault(pr, {})[side] = f"{pr}{side}"
                    # layout: RUN/<pr>/cells/<side>/<task>/<cell>.json
                    cell = os.path.join(d, pr, "cells", side, "t", "c.json")
                    os.makedirs(os.path.dirname(cell), exist_ok=True)
                    json.dump({"probe_method": method, "provider_loaded_version": "2.0.58"}, open(cell, "w"))
            pins = {f"{pr}{s}": {s: {"packages": {"@ai-sdk/anthropic": "2.0.58"}}}
                    for pr, v in sides.items() for s in v}
            out, rc = evaluate(d, pins, sides)
            self.assertEqual(rc, 0, out["mismatch_sides"])
            self.assertEqual(out["sides_seen"], 22)
            self.assertIn("embedded 2.0.58", {c["why"] for c in out["cells"]})


def _req(model, tools=None, wd="/tmp/a", extra=None):
    body = {"model": model, "system": [{"type": "text", "text": f"hi\n  Working directory: {wd}\nbye"}],
            "messages": [], "stream": True}
    if tools is not None:
        body["tools"] = [{"name": t} for t in tools]
    body.update(extra or {})
    return _norm({"method": "POST", "path": "/v1/messages", "headers": {}, "body": json.dumps(body)})


class RequestCompareTest(unittest.TestCase):
    def test_reordered_requests_and_workdir_match(self):
        a = [_req("haiku", wd="/tmp/a"), _req("opus", ["bash", "read"], wd="/tmp/a")]
        b = [_req("opus", ["bash", "read"], wd="/tmp/b"), _req("haiku", wd="/tmp/b")]
        bad, notes = compare_requests(a, b)
        self.assertEqual((bad, notes), ([], []))

    def test_shape_difference_fails(self):
        bad, _ = compare_requests([_req("opus", ["bash"])], [_req("opus", ["bash"], extra={"temperature": 0})])
        self.assertTrue(bad)

    def test_tool_list_difference_fails(self):
        bad, _ = compare_requests([_req("opus", ["bash"])], [_req("opus", ["read"])])
        self.assertTrue(any("tools" in x for x in bad))

    def test_different_endpoints_fail(self):
        bad, _ = compare_requests([_req("opus")], [_req("haiku")])
        self.assertTrue(bad)

    def test_content_diff_outside_workdir_is_a_note(self):
        x = _req("opus", ["bash"])
        y = _req("opus", ["bash"])
        y["body"]["messages"] = [1]
        z = _req("opus", ["bash"])
        z["body"]["messages"] = [2]
        bad, notes = compare_requests([y], [z])
        self.assertEqual(bad, [])
        self.assertTrue(notes)


if __name__ == "__main__":
    unittest.main()
