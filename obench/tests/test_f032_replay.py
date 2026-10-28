"""Replay the fixed projection on the merged F03-2 run (41877c92).

No model calls. The live 03:44 HOLD came from the old flat-average projection
(extrapolating PR 3251's cost to every cell). The fixed code also holds at $60,
but for a different reason (its $63.94 projection exceeds $60), so this does
not show agreement with the live decision. What the replay shows is that the
resume was correct: $63.94 < $70 stop and $54.50 scored spend < $65.89 resume cap.
"""
import unittest
from pathlib import Path

from thesis.ab.replay_f032 import report

OUT = Path(__file__).resolve().parents[2] / "data" / "f032-replay-1027.txt"


class F032ReplayTests(unittest.TestCase):
    def test_replay_matches_committed_output(self):
        text = report()
        self.assertEqual(text, OUT.read_text())
        self.assertIn("total_spend_usd: 58.61\n", text)
        self.assertIn("resume_projected_usd: 63.941\n", text)
        self.assertIn("resume_decision_stop_70: RESUME\n", text)
        self.assertIn("resume_decision_stop_60_configured: HOLD\n", text)
        self.assertIn("final_spend_under_stop_70: yes\n", text)
        self.assertIn("final_spend_under_stop_60: yes\n", text)
        self.assertIn("scored_spend_under_resume_cap: yes\n", text)
        self.assertIn("off_route 0", text)
        self.assertIn("does not show agreement with the live decision", text)
        self.assertIn("$63.94 < $70 stop and $54.50 scored spend < $65.89 resume cap", text)


if __name__ == "__main__":
    unittest.main()
