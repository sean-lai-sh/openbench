import json
import tempfile
import unittest
from pathlib import Path

from thesis.ab.run_ab import (
    _absorb_pr_early_stop, _pr_stop_key, apply_cell_meter, pr_early_stop,
)
from thesis.ab.summarize import (
    ONE_SIDE_STRIP, diff_touches_sampling, params_strip_status,
)
from thesis.ab.vertex_anthropic_proxy import _append_ledger


def _cell(i, cls):
    return {"ts_iso": f"2026-10-17T00:00:{i:02d}+00:00", "failure_class": cls,
            "success": cls == "solved"}


class PrEarlyStopTests(unittest.TestCase):
    def test_four_infra_in_first_ten_stops(self):
        rows = [_cell(i, "infra" if i < 4 else "solved") for i in range(10)]
        self.assertIn("4 of the first 10", pr_early_stop(rows))

    def test_three_infra_is_fine_and_later_infra_ignored(self):
        rows = [_cell(i, "infra" if i < 3 else "solved") for i in range(10)]
        rows += [_cell(10 + i, "infra") for i in range(5)]
        self.assertIsNone(pr_early_stop(rows))

    def test_stops_before_ten_once_four_infra(self):
        self.assertIsNotNone(pr_early_stop([_cell(i, "infra") for i in range(4)]))

    def test_absorb_marks_pr_and_writes_sidecar(self):
        out = Path(tempfile.mkdtemp())
        for i in range(5):
            side = "with" if i % 2 else "without"
            d = out / "7" / "cells" / side / "t"
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{i + 1}.json").write_text(json.dumps(_cell(i, "infra")))
        prepared = {}
        _absorb_pr_early_stop({"pr": "7", "side": "with"}, out, prepared)
        self.assertFalse(prepared[_pr_stop_key("7")]["ok"])
        self.assertTrue((out / "7" / "early-stop.json").is_file())


class ParamsStrippedTests(unittest.TestCase):
    def test_cell_counts_requests_with_stripped_params(self):
        ledger = Path(tempfile.mkdtemp())
        usage = {"input_tokens": 1, "output_tokens": 1}
        _append_ledger(ledger, "c1", usage, status=200, identity={
            "stripped": False, "removed": [], "normalized": [],
            "sampling_params_removed": ["param:temperature"]})
        _append_ledger(ledger, "c1", usage, status=200, identity={
            "stripped": False, "removed": [], "normalized": []})
        row = apply_cell_meter({}, {"ledger_dir": str(ledger), "cell_id": "c1"})
        self.assertEqual(row["params_stripped_requests"], 1)
        self.assertEqual(row["params_stripped"], ["param:temperature"])

    def test_strip_status(self):
        s = [{"params_stripped_requests": 3}]
        n = [{"params_stripped_requests": 0}]
        self.assertEqual(params_strip_status(s, s), "both")
        self.assertEqual(params_strip_status(n, n), "none")
        self.assertEqual(params_strip_status(n, s), ONE_SIDE_STRIP)
        self.assertEqual(params_strip_status(s, n), ONE_SIDE_STRIP)
        self.assertEqual(params_strip_status(s, s, True), "untestable-as-is")

    def test_diff_touches_sampling(self):
        self.assertTrue(diff_touches_sampling("+  temperature: 0.55,\n"))
        self.assertTrue(diff_touches_sampling("-    topP: 1\n"))
        self.assertFalse(diff_touches_sampling(" temperature: 1\n+other\n"))
        self.assertFalse(diff_touches_sampling("+++ b/temperature.ts\n"))


class SummaryWiringTests(unittest.TestCase):
    def test_pr_record_csv_and_markdown_carry_strip_status_and_early_stop(self):
        import csv as _csv
        import io
        from obench.tests.test_no_progress import _pr
        from thesis.ab.summarize import pr_record, render_csv, render_markdown
        out = Path(tempfile.mkdtemp())
        for side, n in (("without", 0), ("with", 2)):
            d = out / "9" / "cells" / side / "t"
            d.mkdir(parents=True)
            row = {"task": "t", "trial": 1, "score": 1, "success": True,
                   "failure_class": "solved", "params_stripped_requests": n}
            (d / "1.json").write_text(json.dumps(row))
            (out / "9" / f"{side}.jsonl").write_text(json.dumps(row) + "\n")
        (out / "9" / "early-stop.json").write_text(json.dumps({"reason": "pr early stop: 4 of the first 10"}))
        record = pr_record(_pr(), out)
        self.assertEqual(record["params_strip_status"], ONE_SIDE_STRIP)
        self.assertIn("4 of the first 10", record["early_stop"])
        parsed = list(_csv.DictReader(io.StringIO(render_csv([record]))))
        self.assertEqual(parsed[0]["params_strip_status"], ONE_SIDE_STRIP)
        text = render_markdown([record])
        self.assertIn(f"Sampling params stripped: {ONE_SIDE_STRIP}.", text)
        self.assertIn("Early stop: pr early stop", text)
