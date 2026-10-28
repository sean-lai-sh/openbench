"""One cell end to end: run_cell (fake adapter) -> run_ab metadata -> cell
file -> step8_gate. Every field the gate/scorer reads must be on the file."""
import json, os, re, tempfile, unittest
from pathlib import Path
from unittest import mock

from thesis.ab import run_ab, step8_gate
from obench.tests.test_phase_timing import TestPhaseTiming

PROBED = {"provider_loaded_version": "2.0.0", "provider_loaded_source": "strace", "probe_method": "strace"}
SHA = {"with": "a" * 40, "without": "b" * 40}
PINS = {s: {side: {"packages": {"@ai-sdk/anthropic": "2.0.0"}}} for side, s in SHA.items()}
NOT_CELL = {"packages", "ok_prs", "mismatch_sides", "halted_at", "missing_fields"}


def gate_reads() -> set[str]:
    """Cell keys step8_gate reads, from its source (new reads are covered)."""
    src = Path(step8_gate.__file__).read_text()
    return set(re.findall(r'\bc(?:ell)?\.get\("([a-z_0-9]+)"', src)) - NOT_CELL


class CellFieldCompleteness(TestPhaseTiming):
    def _cell(self, d, side, extra_env=None, stamp=True, proxy=None, trial=0):
        binary = Path(d) / "bin" / SHA[side] / "opencode"
        binary.parent.mkdir(parents=True, exist_ok=True)
        if stamp:
            (binary.parent / "build-stamp.json").write_text(json.dumps({"build_channel": "local"}))
        spec = dict(pr="1", side=side, sha=SHA[side], task="t", trial=trial, binary=str(binary),
                    cell_meta={"cell_image": "h1-env:1027-strace", "runner_commit": "c" * 40},
                    proxy=proxy if proxy is not None else
                    {"route": "provider options", "opencode_cache": "/c", "lockfile_sha256": "f" * 64})
        env = {"OBENCH_PROVIDER_TRACE": "1", **(extra_env or {})}
        with mock.patch.dict(os.environ, env):
            row = self._run_with_fakes(extra_result=dict(PROBED))
            row["requests_cost_usd"] = 0.1
            row["route"] = "on:provider-options"  # apply_cell_meter sets this from the ledger
            run_ab.attach_cell_meta(row, spec, "2026-10-27T03:00:00-04:00")
            run_ab.attach_provider_pin(row, spec)
            run_ab.attach_required_fields(row, spec)
        path = run_ab.cell_file(Path(d) / "run", "1", side, "t", trial)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(row))
        return json.loads(path.read_text())

    def test_required_list_covers_gate_reads(self):
        self.assertLessEqual(gate_reads(), set(run_ab.REQUIRED_CELL_FIELDS))
        for k in ("route", "rerun", "cell_image", "provider_trace", "opencode_cache", "lockfile_sha256",
                  "build_channel", "probe_method", "provider_loaded_version", "provider_loaded_source",
                  "provider_loaded_mismatch"):
            self.assertIn(k, run_ab.REQUIRED_CELL_FIELDS)

    def test_saved_cell_has_every_field_and_passes_gate(self):
        with tempfile.TemporaryDirectory() as d:
            saved = {side: self._cell(d, side) for side in SHA}
            for side, c in saved.items():
                for k in run_ab.REQUIRED_CELL_FIELDS:
                    self.assertIn(k, c, k)
                self.assertNotIn("missing_fields", c)
                self.assertEqual((c["cell_image"], c["provider_trace"], c["build_channel"], c["rerun"]),
                                 ("h1-env:1027-strace", "on" if __import__("shutil").which("strace") else "off", "local", 0))
                self.assertEqual((c["opencode_cache"], c["lockfile_sha256"]), ("/c", "f" * 64))
            out, _ = step8_gate.evaluate(str(Path(d) / "run"), PINS, {"1": SHA})
            self.assertEqual(out["ok_prs"], ["1"], out["cells"])
            # halted_spend is per side in route_check, not per cell.
            route, _ = step8_gate.route_check(str(Path(d) / "run"))
            self.assertIn("halted_spend", route)
            done, _ = step8_gate.complete(str(Path(d) / "run"), out)
            self.assertIn("1/with", done["incomplete"])  # 1 cell, not 30: not padded

    def test_traced_gate_cell_excluded_from_31(self):
        """31 cells on one side, one traced gate cell: exactly 30 scored."""
        with tempfile.TemporaryDirectory() as d:
            gate = {"ok_prs": ["1"], "mismatch_sides": []}
            traced = self._cell(d, "with", {"OBENCH_PROVIDER_TRACE": "1", "OBENCH_GATE_CELL": "1"}, trial=0)
            self.assertIs(traced["gate_cell"], True)
            for t in range(1, 31):
                c = self._cell(d, "with", {"OBENCH_PROVIDER_TRACE": "0", "OBENCH_GATE_CELL": "0"}, trial=t)
                self.assertIs(c["strace_on"], False)
                self.assertIs(c["gate_cell"], False)
            done, _ = step8_gate.complete(str(Path(d) / "run"), gate)
            side = done["complete"]["1/with"]
            self.assertEqual(side["on_route"], 30)
            self.assertEqual(len(side["cells"]), 30)
            tf = str(run_ab.cell_file(Path(d) / "run", "1", "with", "t", 0))
            self.assertEqual(done["excluded_traced"], [tf])
            self.assertNotIn(tf, side["cells"])
            # Dropping the marker must not silently score the traced cell.
            p = Path(tf); c = json.loads(p.read_text()); c.pop("gate_cell"); c["strace_on"] = False
            p.write_text(json.dumps(c))
            done, _ = step8_gate.complete(str(Path(d) / "run"), gate)
            self.assertEqual(done["excluded_traced"], [])  # proves the test catches a dropped marker

    def test_rerun_tag_saved(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self._cell(d, "with", {"OBENCH_RERUN": "1"})["rerun"], 1)

    def test_missing_field_recorded_and_fails_gate(self):
        with tempfile.TemporaryDirectory() as d:
            for side in SHA:
                c = self._cell(d, side, stamp=False, proxy={"route": "provider options"})
            self.assertEqual(sorted(c["missing_fields"]), ["build_channel", "lockfile_sha256", "opencode_cache"])
            self.assertIsNone(c["build_channel"])
            out, _ = step8_gate.evaluate(str(Path(d) / "run"), PINS, {"1": SHA})
            self.assertEqual(out["ok_prs"], [])
            self.assertIn("cell missing fields", out["cells"][0]["why"])

    def test_untraced_cell_may_omit_probe_fields(self):
        """strace_on false: probe_method and provider_loaded_version are optional."""
        with tempfile.TemporaryDirectory() as d:
            c = self._cell(d, "with", {"OBENCH_PROVIDER_TRACE": "0", "OBENCH_GATE_CELL": "0"})
            self.assertIs(c["strace_on"], False)
            c.pop("probe_method", None)
            c["provider_loaded_version"] = None
            run_ab.attach_required_fields(c, {})
            self.assertNotIn("missing_fields", c)
            self.assertIsNone(c["probe_method"])
            self.assertIsNone(c["provider_loaded_version"])

    def test_traced_cell_requires_probe_fields(self):
        """strace_on true, including gate cells: both probe fields are required."""
        with tempfile.TemporaryDirectory() as d:
            c = self._cell(d, "with", {"OBENCH_PROVIDER_TRACE": "1", "OBENCH_GATE_CELL": "1"})
            c["strace_on"] = True
            c.pop("probe_method", None)
            c["provider_loaded_version"] = ""
            run_ab.attach_required_fields(c, {"pr": "1", "side": "with"})
            self.assertEqual(sorted(c["missing_fields"]), ["probe_method", "provider_loaded_version"])
            ok, why = step8_gate.judge(c, "2.0.0")
            self.assertFalse(ok)
            self.assertIn("probe_method", why)
            self.assertIn("provider_loaded_version", why)
            filled = dict(c, probe_method="strace", provider_loaded_version="2.0.0")
            run_ab.attach_required_fields(filled, {})
            self.assertNotIn("missing_fields", filled)
            self.assertTrue(step8_gate.judge(filled, "2.0.0")[0])


ROOT = Path(__file__).resolve().parents[2]
F032 = ROOT / "results" / "step8-f032-1027"


class F032FieldCompleteness(unittest.TestCase):
    """Re-check the F03-2 cells with the untraced-probe rule."""

    def test_scored_cells_have_no_missing_fields_and_gate_cells_pass(self):
        self.assertTrue((F032 / "scored").is_dir(), F032)
        scored = sorted((F032 / "scored").glob("*/cells/*/*/*.json"))
        self.assertEqual(len(scored), 660)
        for path in scored:
            row = json.loads(path.read_text())
            self.assertIs(row.get("strace_on"), False, path)
            fresh = dict(row)
            run_ab.attach_required_fields(fresh, {})
            self.assertNotIn("missing_fields", fresh, path)
        gate_doc = json.loads((F032 / "gate.json").read_text())
        pins = {c["cell"]: c["pin"] for c in gate_doc["cells"]}
        gate_paths = sorted((F032 / "gate").glob("*/cells/*/*/*.json"))
        self.assertEqual(len(gate_paths), 22)
        self.assertEqual(len(gate_paths), len(pins))
        for path in gate_paths:
            rel = str(path.relative_to(F032 / "gate"))
            row = json.loads(path.read_text())
            self.assertIs(row.get("strace_on"), True, path)
            fresh = dict(row)
            run_ab.attach_required_fields(fresh, {})
            self.assertNotIn("missing_fields", fresh, path)
            ok, why = step8_gate.judge(fresh, pins[rel])
            self.assertTrue(ok, (rel, why))


if __name__ == "__main__":
    unittest.main()
