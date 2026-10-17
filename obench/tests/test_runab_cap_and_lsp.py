"""run_ab: --max-cost-usd counts cells already in --out; roslyn pre-install runs once."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from obench.lsp_cell import LspProvisionError
from thesis.ab.run_ab import _preinstall_shared_lsp, over_budget
from thesis.ab.summarize import row_cost


def _cell(out: Path, pr: str, side: str, trial: int) -> dict:
    row = {
        "task": "make-it-run", "trial": trial, "score": 1, "success": True,
        "failure_class": "solved", "model": "claude-opus-5-5",
        "tokens_input_uncached": 1000, "tokens_output": 2000,
        "tokens_cache_read": 30000, "tokens_cache_write": 4000,
    }
    path = out / pr / "cells" / side / "make-it-run" / f"{trial}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row), encoding="utf-8")
    return row


class CapCountsExistingCellsTests(unittest.TestCase):
    def test_cells_from_an_earlier_batch_in_the_same_out_dir_count(self):
        out = Path(tempfile.mkdtemp())
        earlier = [_cell(out, "21070", "without", 1), _cell(out, "21070", "with", 1)]
        spent = sum(row_cost(row) for row in earlier)
        self.assertGreater(spent, 0)
        # A later batch (another PR) in the same dir starts with the earlier spend.
        self.assertIsNone(over_budget(out, spent * 1.5))
        reason = over_budget(out, spent * 0.99)
        self.assertIsNotNone(reason)
        self.assertIn("cap", reason)


class PreinstallRoslynTests(unittest.TestCase):
    def test_runs_once_only_when_a_cell_needs_dotnet(self):
        calls = []

        def ensure():
            calls.append(1)
            return "/shared/roslyn"

        pending = [
            {"fixtures": {"lsp": ["dotnet"]}},
            {"fixtures": {"lsp": "dotnet"}},
            {"fixtures": {}},
        ]
        self.assertIsNone(_preinstall_shared_lsp(pending, ensure_fn=ensure))
        self.assertEqual(len(calls), 1)
        self.assertIsNone(_preinstall_shared_lsp([{"fixtures": {"lsp": ["pyright"]}}], ensure_fn=ensure))
        self.assertEqual(len(calls), 1)

    def test_failure_is_reported_not_raised(self):
        def ensure():
            raise LspProvisionError("dotnet failed: timed out after 600 seconds")

        reason = _preinstall_shared_lsp([{"fixtures": {"lsp": ["dotnet"]}}], ensure_fn=ensure)
        self.assertIn("timed out", reason)


if __name__ == "__main__":
    unittest.main()
