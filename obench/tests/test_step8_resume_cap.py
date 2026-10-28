"""Resume must count each cell's spend once.

The launcher used to set --max-cost-usd to stop minus spend(), and spend()
includes cells already in the phase directory. run_ab.over_budget sums those
same cells again. A $60 stop with $5 of gate spend and $25 already scored
left about $5 of room instead of $30.
"""
import glob
import json
import os
import tempfile
import unittest
from pathlib import Path

from thesis.ab.run_ab import over_budget
from thesis.ab.summarize import row_cost

ROOT = Path(__file__).resolve().parents[2]
SHELL = ROOT / "thesis/ab/launchers/step8_f032.sh"


def _usd_cell(usd: float) -> dict:
    """A cell whose requests_cost_usd and over_budget row_cost are both ``usd``.

    Sonnet 5.5 output is $10 / MTok, so ``usd`` dollars is ``usd * 100_000``
    output tokens.
    """
    tokens = usd * 1_000_000 / 10.0
    if tokens != int(tokens):
        raise ValueError(usd)
    return {
        "requests_input_uncached": 0,
        "requests_output": int(tokens),
        "requests_cache_read": 0,
        "requests_cache_write": 0,
        "requests_cost_usd": usd,
        "upstream_model": "claude-sonnet-5-5",
        "failure_class": "solved",
        "route": "on:provider-options",
    }


def _write(run: Path, phase: str, trial: int, usd: float) -> dict:
    row = _usd_cell(usd)
    path = run / phase / "1" / "cells" / "with" / "task" / f"{trial}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row))
    return row


def _dir_cost(phase_dir: Path) -> float:
    total = 0.0
    for path in phase_dir.glob("*/*/*/*/*.json"):
        total += row_cost(json.loads(path.read_text()))
    return total


def launcher_cap(run_dir: str, phase: str, stop: float, prior: float) -> float:
    """The cap the launcher script would pass to run_ab for ``phase``."""
    sh = SHELL.read_text()
    if "--phase-cap" in sh:
        from thesis.ab.step8_project import phase_cap
        return phase_cap(run_dir, phase, stop, prior)
    # Pre-fix launcher: CAP = stop - spend(), and spend() includes this phase.
    spent = prior
    for f in glob.glob(os.path.join(run_dir, "[gsr]*", "*", "cells", "*", "*", "*.json")):
        with open(f) as fh:
            spent += json.load(fh).get("requests_cost_usd") or 0
    return round(stop - spent, 2)


class ResumeCapTests(unittest.TestCase):
    def test_resume_counts_each_cell_once(self):
        # $60 stop, $5 gate, $25 already scored. Remaining new spend is $30.
        with tempfile.TemporaryDirectory() as d:
            run = Path(d)
            _write(run, "gate", 0, 5)
            _write(run, "scored", 0, 25)
            cap = launcher_cap(d, "scored", 60, 0)
            self.assertEqual(cap, 55.0)
            scored = run / "scored"
            self.assertEqual(_dir_cost(scored), 25.0)
            self.assertIsNone(over_budget(scored, cap))
            # Room for new scored spend is the $30 that has not been spent yet.
            self.assertEqual(cap - _dir_cost(scored), 30.0)
            # Prior is subtracted once. The $25 already scored still is not.
            self.assertEqual(launcher_cap(d, "scored", 60, 2), 53.0)
            _write(run, "scored", 1, 30)
            self.assertIsNotNone(over_budget(scored, cap))
        # Resuming reruns: gate $5 and scored $25 are outside the rerun
        # directory. The $4 already in rerun is left for over_budget.
        with tempfile.TemporaryDirectory() as d:
            run = Path(d)
            _write(run, "gate", 0, 5)
            _write(run, "scored", 0, 25)
            _write(run, "rerun", 0, 4)
            rcap = launcher_cap(d, "rerun", 60, 0)
            self.assertEqual(rcap, 30.0)
            self.assertEqual(rcap - _dir_cost(run / "rerun"), 26.0)
            self.assertIsNone(over_budget(run / "rerun", rcap))
        sh = SHELL.read_text()
        self.assertIn("--phase-cap scored", sh)
        self.assertIn("--phase-cap rerun", sh)
        self.assertNotIn("STOP_USD-$(spend)", sh)


if __name__ == "__main__":
    unittest.main()
