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
    def _cell(self, d, side, extra_env=None, stamp=True, proxy=None):
        binary = Path(d) / "bin" / SHA[side] / "opencode"
        binary.parent.mkdir(parents=True, exist_ok=True)
        if stamp:
            (binary.parent / "build-stamp.json").write_text(json.dumps({"build_channel": "local"}))
        spec = dict(pr="1", side=side, sha=SHA[side], task="t", trial=0, binary=str(binary),
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
        path = run_ab.cell_file(Path(d) / "run", "1", side, "t", 0)
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


if __name__ == "__main__":
    unittest.main()
