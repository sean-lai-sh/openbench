import json, tempfile, unittest
from pathlib import Path
from thesis.ab import step8_project as sp

G = {("1", "with"): 0.2, ("1", "without"): 0.2, ("2", "with"): 0.1, ("2", "without"): 0.1}


class Projection(unittest.TestCase):
    def test_fallback_before_any_pr_done(self):
        out = sp.project(G, {}, spent=2.0, prior=1.0, n=30)
        self.assertEqual(out["pooled_ratio_used"], 1.0)
        self.assertAlmostEqual(out["projected"], 3.0 + 30 * (0.4 + 0.2))

    def test_own_ratio_wins_when_higher_else_pooled(self):
        scored = {("1", "with"): [0.1] * 30, ("1", "without"): [0.1] * 30,  # pooled 0.5
                  ("2", "with"): [0.2] * 10}  # own 2.0
        out = sp.project(G, scored, spent=0, n=30)
        self.assertEqual(out["done_prs"], ["1"])
        self.assertAlmostEqual(out["pooled_ratio"], 0.5)
        self.assertAlmostEqual(out["per_pr"]["2"]["ratio"], 2.0)
        self.assertAlmostEqual(out["remaining"], (20 * 0.1 + 30 * 0.1) * 2.0)
        scored[("2", "with")] = [0.01] * 10  # own 0.1 < pooled
        self.assertAlmostEqual(sp.project(G, scored, 0, n=30)["per_pr"]["2"]["ratio"], 0.5)

    def test_partial_pr_own_ratio_over_fallback(self):
        # 03:44 case: only PR 1 partly done, cheaper than its gate cells -> fallback 1.0 used.
        out = sp.project(G, {("1", "with"): [0.16] * 12, ("1", "without"): [0.16] * 12}, 0, n=30)
        self.assertAlmostEqual(out["per_pr"]["1"]["ratio"], 1.0)
        self.assertAlmostEqual(out["remaining"], 36 * 0.2 + 60 * 0.1)

    def test_cli_halts_over_stop(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "gate.json").write_text(json.dumps({"ok_prs": ["1"], "cells": [
                {"pr": "1", "side": "with", "cost": 1.0}, {"pr": "1", "side": "without", "cost": 1.0}]}))
            f = Path(d, "scored", "1", "cells", "with", "t", "0.json"); f.parent.mkdir(parents=True)
            f.write_text(json.dumps({"requests_cost_usd": 1.0}))
            self.assertEqual(sp.main([d, "--prior", "2", "--stop", "70"]), 0)  # 3 + 59
            self.assertEqual(sp.main([d, "--prior", "2", "--stop", "60"]), 1)


if __name__ == "__main__":
    unittest.main()
