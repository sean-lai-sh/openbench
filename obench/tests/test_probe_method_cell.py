"""probe_method survives adapter result -> run_cell row -> cell file -> step8_gate;
a pair must take one route (OBENCH_FORCE_ROUTE, pair_route_split)."""
import json, os, tempfile, unittest
from pathlib import Path
from unittest import mock

from obench import run
from obench.tests.test_phase_timing import TestPhaseTiming
from thesis.ab import compat, run_ab, step8_gate

SHA = {"with": "e88b659545245888ee4091a0cc353f4d7bda7327", "without": "74048ece2d06dd8c3b6f9be46a10ae0c927e13db"}
PINS = {s: {side: {"packages": {"@ai-sdk/anthropic": "2.0.0"}}} for side, s in SHA.items()}
SIDES = {"3424": dict(SHA)}
PROBED = {"provider_loaded_version": "2.0.0", "provider_loaded_source": "strace", "probe_method": "strace"}


class ProbeMethodEndToEnd(TestPhaseTiming):
    def _write(self, out, side, row, route="on:provider-options"):
        row = dict(row, route=route)
        path = run_ab.cell_file(out, "3424", side, "t", 0)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(row))

    def test_adapter_probe_method_reaches_gate(self):
        row = self._run_with_fakes(extra_result=dict(PROBED))
        self.assertEqual(row["probe_method"], "strace")
        self.assertEqual(row["provider_loaded_source"], "strace")
        run_ab.attach_provider_pin(row, {"proxy": {}})
        self.assertEqual(row["probe_method"], "strace")
        with tempfile.TemporaryDirectory() as d:
            for side in SHA:
                self._write(Path(d), side, row)
            out, rc = step8_gate.evaluate(d, PINS, SIDES)
        self.assertEqual(out["ok_prs"], ["3424"], out["cells"])
        self.assertTrue(all(c["probe_method"] == "strace" for c in out["cells"]))

    def test_embedded_source_kept(self):
        row = self._run_with_fakes(extra_result=dict(PROBED, provider_loaded_source="embedded", probe_method="embedded"))
        self.assertEqual((row["provider_loaded_source"], row["probe_method"]), ("embedded", "embedded"))

    def test_bogus_probe_method_not_copied(self):
        row = self._run_with_fakes(extra_result=dict(PROBED, probe_method="guess"))
        self.assertNotIn("probe_method", row)

    def test_old_cell_shape_still_unproven(self):
        # 2026-10-27 gate cells (no probe_method): the gate is not loosened.
        old = {k: v for k, v in PROBED.items() if k != "probe_method"}
        with tempfile.TemporaryDirectory() as d:
            for side in SHA:
                self._write(Path(d), side, old)
            out, _ = step8_gate.evaluate(d, PINS, SIDES)
        self.assertEqual(out["ok_prs"], [])
        self.assertTrue(all(c["why"] == "loaded version unproven" for c in out["cells"]))

    def test_gate_fails_pair_with_split_route(self):
        with tempfile.TemporaryDirectory() as d:
            self._write(Path(d), "with", PROBED)
            self._write(Path(d), "without", PROBED, route="on:base-url-env")
            out, _ = step8_gate.evaluate(d, PINS, SIDES)
        self.assertEqual(out["ok_prs"], [])
        self.assertEqual(out["mismatch_sides"], ["3424/with", "3424/without"])
        self.assertIn("pair route differs", out["cells"][0]["why"])


class CompleteSplitRoute(unittest.TestCase):
    def test_complete_rejects_split_pair(self):
        with tempfile.TemporaryDirectory() as s:
            for side, how in (("with", "provider-options"), ("without", "base-url-env")):
                for i in range(30):
                    p = Path(s) / "3424" / "cells" / side / "t" / f"{i}.json"
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(json.dumps({"route": f"on:{how}"}))
            out, _ = step8_gate.complete(s, {"ok_prs": ["3424"], "mismatch_sides": []})
        self.assertEqual(out["complete"], {})
        self.assertIn("pair route differs", out["incomplete"]["3424/with"]["why"])


class ForcedRoute(unittest.TestCase):
    def _assess(self, listed_seq, forced):
        calls = iter(listed_seq)
        with mock.patch.dict(os.environ, {"OBENCH_FORCE_ROUTE": forced}), \
             mock.patch.object(compat, "_models_text", side_effect=lambda *a: (0, "x")), \
             mock.patch.object(compat, "_model_listed", side_effect=lambda t: next(calls)), \
             mock.patch.object(compat, "_needs_host_sdk", return_value=False):
            return compat._assess_proxy("/bin/opencode", False, "http://127.0.0.1:9/")

    def test_flaky_first_probe_retried_not_env_fallback(self):
        a = self._assess([False, True], "provider-options")
        self.assertEqual(a.proxy["route"], "provider options")

    def test_forced_never_listed_is_infra(self):
        a = self._assess([False, False, False], "provider-options")
        self.assertEqual(a.status, "infra"); self.assertIn("forced route", a.reason)

    def test_unforced_falls_back_as_before(self):
        a = self._assess([False, True, True], "")
        self.assertEqual(a.proxy["route"], "ANTHROPIC_BASE_URL")


if __name__ == "__main__":
    unittest.main()
