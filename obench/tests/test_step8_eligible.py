"""Projection counts the same scored cells as step8_gate.complete().

Off-route cells stay in spent and do not count toward the 30. A tagged
on-route rerun replaces its off-route original and does count.
"""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from thesis.ab import step8_gate, step8_project


def _cell(root, phase, pr, side, trial, route, cost, rerun=0):
    path = Path(root) / phase / pr / "cells" / side / "task" / f"{trial}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "requests_cost_usd": cost, "route": route, "rerun": rerun,
        "strace_on": False, "gate_cell": False,
    }))


class EligibleScoredTests(unittest.TestCase):
    def test_off_route_cells_agree_with_complete(self):
        with tempfile.TemporaryDirectory() as d:
            gate = {
                "ok_prs": ["1"], "mismatch_sides": [],
                "cells": [
                    {"pr": "1", "side": "with", "cost": 0.2},
                    {"pr": "1", "side": "without", "cost": 0.2},
                ],
            }
            Path(d, "gate.json").write_text(json.dumps(gate))
            for side in ("with", "without"):
                for i in range(2):
                    _cell(d, "scored", "1", side, i, "off:provider-options", 0.5)
                for i in range(2, 30):
                    _cell(d, "scored", "1", side, i, "on:provider-options", 0.1)
            # Tagged reruns replace the two off-route without-side originals.
            for i in range(2):
                _cell(d, "rerun", "1", "without", i, "on:provider-options", 0.3, rerun=1)
            comp, _ = step8_gate.complete(
                os.path.join(d, "scored"), gate, [os.path.join(d, "rerun")])
            self.assertEqual(comp["complete"]["1/without"]["on_route"], 30)
            self.assertEqual(comp["complete"]["1/without"]["reruns"], 2)
            self.assertEqual(comp["incomplete"]["1/with"]["on_route"], 28)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                step8_project.main([d, "--prior", "0", "--stop", "1000"])
            out = json.loads(buf.getvalue())
            # Off-route cost is still spent: 2 sides * (28*0.1 + 2*0.5) + 2*0.3.
            self.assertAlmostEqual(out["spent"], 8.2)
            finished = []
            for pr in ("1",):
                sides = [k for k in ("1/with", "1/without")]
                if all(k in comp["complete"] for k in sides):
                    finished.append(pr)
            self.assertEqual(out["done_prs"], finished)
            # with-side still needs 2 cells. Own ratio uses the rerun costs
            # (0.3), not the off-route originals (0.5).
            self.assertNotIn("1", out["done_prs"])
            self.assertAlmostEqual(out["per_pr"]["1"]["own_ratio"], 6.2 / 11.6)
            self.assertAlmostEqual(out["remaining"], 0.4)


if __name__ == "__main__":
    unittest.main()
