import json
import os
import tempfile
import unittest

from obench.provider_embedded import embedded_version, scan
from thesis.ab.route import how_of, off_route, route_label
from thesis.ab.step8_gate import evaluate, judge, route_check
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
        ok, why = judge({"loaded_anthropic": "2.0.58", "probe_method": "embedded", "provider_loaded_version": "2.0.58"}, "2.0.58")
        self.assertTrue(ok, why)

    def test_embedded_other_version_is_mismatch(self):
        ok, why = judge({"loaded_anthropic": "2.0.58", "probe_method": "embedded", "provider_loaded_version": "2.0.57"}, "2.0.58")
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
                    json.dump({"loaded_anthropic": "2.0.58", "probe_method": method, "provider_loaded_version": "2.0.58",
                               "route": "on:provider-options"}, open(cell, "w"))
            pins = {f"{pr}{s}": {s: {"packages": {"@ai-sdk/anthropic": "2.0.58"}}}
                    for pr, v in sides.items() for s in v}
            out, rc = evaluate(d, pins, sides)
            self.assertEqual(rc, 0, out["mismatch_sides"])
            self.assertEqual(out["sides_seen"], 22)
            self.assertIn("user-agent 2.0.58, embedded 2.0.58", {c["why"] for c in out["cells"]})


def _cells(d, routes):
    """routes: {(pr, side): [route, ...]} -> one cell file per route."""
    for (pr, side), rs in routes.items():
        for i, r in enumerate(rs):
            cell = os.path.join(d, pr, "cells", side, f"t{i}", "c.json")
            os.makedirs(os.path.dirname(cell), exist_ok=True)
            json.dump({} if r is None else {"route": r}, open(cell, "w"))


class RouteTest(unittest.TestCase):
    def test_label(self):
        self.assertEqual(route_label({"route": "provider options"}, 3), "on:provider-options")
        self.assertEqual(route_label({"route": "ANTHROPIC_BASE_URL"}, 0), "off:base-url-env")
        self.assertEqual(how_of(None), "none")
        self.assertTrue(off_route({"route": "off:base-url-env"}))
        self.assertFalse(off_route({"route": "on:base-url-env"}))

    def test_off_route_gate_cell_is_infra(self):
        with tempfile.TemporaryDirectory() as d:
            sides, pins = {}, {}
            for i in range(11):
                pr = str(100 + i)
                for side in ("without", "with"):
                    sides.setdefault(pr, {})[side] = f"{pr}{side}"
                    pins[f"{pr}{side}"] = {side: {"packages": {"@ai-sdk/anthropic": "2.0.0"}}}
                    cell = os.path.join(d, pr, "cells", side, "t", "c.json")
                    os.makedirs(os.path.dirname(cell), exist_ok=True)
                    route = "off:base-url-env" if (i, side) == (0, "without") else "on:provider-options"
                    json.dump({"loaded_anthropic": "2.0.0", "probe_method": "strace", "provider_loaded_version": "2.0.0",
                               "route": route}, open(cell, "w"))
            out, rc = evaluate(d, pins, sides)
            self.assertEqual(out["mismatch_sides"], ["100/without"])
            self.assertEqual(rc, 0)
            later, _ = evaluate(d, pins, sides, later=True)
            self.assertEqual(later["rerun"], ["100/cells/without/t/c.json"])

    def test_two_off_route_cells_keep_the_side(self):
        with tempfile.TemporaryDirectory() as d:
            _cells(d, {("1", "with"): ["off:provider-options", "off:base-url-env", "on:base-url-env"]})
            out, rc = route_check(d)
            self.assertEqual(rc, 0)
            self.assertEqual(out["halted_sides"], [])
            self.assertEqual(len(out["rerun"]), 2)
            self.assertEqual(out["label"], "infra:off_route")

    def test_three_off_route_cells_halt_the_side(self):
        with tempfile.TemporaryDirectory() as d:
            _cells(d, {("1", "with"): ["off:a", "off:b", None, "on:a"],
                       ("1", "without"): ["on:a"]})
            out, rc = route_check(d)
            self.assertEqual(out["halted_sides"], ["1/with"])
            self.assertFalse(out["halt_batch"])
            self.assertEqual(rc, 0)

    def test_three_halted_sides_halt_the_batch(self):
        with tempfile.TemporaryDirectory() as d:
            _cells(d, {(str(p), "with"): ["off:x"] * 3 for p in range(3)})
            out, rc = route_check(d)
            self.assertEqual(len(out["halted_sides"]), 3)
            self.assertTrue(out["halt_batch"])
            self.assertEqual(rc, 1)
            _cells(d, {})
        with tempfile.TemporaryDirectory() as d:
            _cells(d, {(str(p), "with"): ["off:x"] * 3 for p in range(2)})
            self.assertEqual(route_check(d)[1], 0)


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
