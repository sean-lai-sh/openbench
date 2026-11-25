"""A/B agreement: probe errors at step 3 or earlier are flagged. Offline; no model calls."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from obench.reflection import credit_a, credit_agreement as agr, credit_b
from obench.tests.test_reflection_credit_a import call, step
from obench.tests.test_reflection_credit_b import FakeJudge


def _run(traces: dict[str, list]) -> Path:
    run = Path(tempfile.mkdtemp())
    trials = []
    for i, (name, trace) in enumerate(traces.items()):
        rel = f"trials/m/t/{i}/trace.jsonl"
        path = run / rel
        path.parent.mkdir(parents=True)
        path.write_text("".join(json.dumps(s) + "\n" for s in trace), encoding="utf-8")
        trials.append({"run_id": "r", "trial_id": name, "task": "t", "model": "m", "patch_id": None,
                       "status": "completed", "passed": False, "trace": rel})
    (run / "trials.jsonl").write_text("".join(json.dumps(t) + "\n" for t in trials), encoding="utf-8")
    credit_a.run_method_a(run)
    credit_b.run_method_b(run, FakeJudge())
    return run


class Agreement(unittest.TestCase):
    def test_probe_error_at_step_3_or_earlier_is_flagged_and_step_4_is_not(self):
        silent = [step(1, call("bash", "ok")), step(2, call("bash", "ok")), step(3, text="done")]
        run = _run({
            "step1": [step(1, call("bash", "file: command not found"))],
            "step3": [step(1, call("bash", "ok")), step(2, call("bash", "ok")),
                      step(3, call("bash", "Traceback (most recent call last):"))],
            "step4": [step(1, call("bash", "ok")), step(2, call("bash", "ok")), step(3, call("bash", "ok")),
                      step(4, call("bash", "error: late"))],
            "silent3": silent,
        })
        rows = {row["trial_id"]: row for row in agr.run_agreement(run)}
        self.assertEqual(agr.main(["--run", str(run)]), 0)
        on_disk = {row["trial_id"]: row for row in
                   (json.loads(line) for line in (run / "credit_agreement.jsonl").read_text().splitlines())}
        self.assertEqual(on_disk, rows)

        self.assertTrue(rows["step1"]["probe_error"])
        self.assertEqual(rows["step1"]["probe_error_step"], 1)
        self.assertEqual(rows["step1"]["method_b_status"], "empty_window")
        self.assertEqual(rows["step1"]["method_b_window_length"], 0)

        self.assertTrue(rows["step3"]["probe_error"])
        self.assertEqual((rows["step3"]["probe_error_step"], rows["step3"]["method_a_step"]), (3, 3))
        self.assertEqual(rows["step3"]["method_b_window_length"], 2)  # k=4, only steps 1 and 2 exist
        self.assertTrue(rows["step3"]["same_step"])

        self.assertFalse(rows["step4"]["probe_error"])
        self.assertIsNone(rows["step4"]["probe_error_step"])
        self.assertEqual(rows["step4"]["method_a_step"], 4)

        # A short trace that ends with no tool error is final_answer_rejected, not a probe.
        self.assertEqual(rows["silent3"]["method_a_signal"], "final_answer_rejected")
        self.assertFalse(rows["silent3"]["probe_error"])
        self.assertEqual(rows["silent3"]["method_a_step"], 3)


if __name__ == "__main__":
    unittest.main()
