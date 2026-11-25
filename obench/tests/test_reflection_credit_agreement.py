"""A/B agreement: probe errors at step 3 or earlier are flagged. Offline; no model calls."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from obench.reflection import credit_a, credit_agreement as agr, credit_b
from obench.tests.test_reflection_credit_a import call, step
from obench.tests.test_reflection_credit_b import FakeJudge


def _draw(run: Path, trial_ids: list[str], cell: str = "m/t") -> None:
    (run / "credit_draw.json").write_text(json.dumps({
        cell: {"status": "IN", "picks": [
            {"draw_order": i + 1, "slot": i, "trial_id": tid} for i, tid in enumerate(trial_ids)]},
    }), encoding="utf-8")


def _run(traces: dict[str, list], drawn: list[str] | None = None, judge=None) -> Path:
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
    _draw(run, list(traces) if drawn is None else drawn)
    credit_a.run_method_a(run)
    credit_b.run_method_b(run, judge or FakeJudge())
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
        self.assertTrue(rows["step3"]["drawn"])
        # The fake judge labels every window step correct, so there is no near-error step.
        self.assertIsNone(rows["step3"]["earliest_near_error_step"])
        self.assertIsNone(rows["step3"]["steps_before_a"])

        self.assertFalse(rows["step4"]["probe_error"])
        self.assertIsNone(rows["step4"]["probe_error_step"])
        self.assertEqual(rows["step4"]["method_a_step"], 4)

        # A short trace that ends with no tool error is final_answer_rejected, not a probe.
        self.assertEqual(rows["silent3"]["method_a_signal"], "final_answer_rejected")
        self.assertFalse(rows["silent3"]["probe_error"])
        self.assertEqual(rows["silent3"]["method_a_step"], 3)
        self.assertIsNone(rows["step1"]["earliest_near_error_step"])
        self.assertIsNone(rows["step1"]["steps_before_a"])

    def test_earliest_near_error_step_and_steps_before_a(self):
        late = [step(n, call("bash", "ok")) for n in range(1, 6)] + [step(6, call("bash", "error: late"))]
        early = [step(1, call("bash", "file: command not found"))]
        run = _run(
            {"late": late, "early": early},
            judge=FakeJudge({4: "near_error", 5: "near_error"}),
        )
        rows = {row["trial_id"]: row for row in agr.run_agreement(run)}
        # Window is steps 2..5 (k=4). The earliest near_error is 4, not 5 and not the window start.
        self.assertEqual(rows["late"]["method_b_window"], [2, 3, 4, 5])
        self.assertEqual(rows["late"]["earliest_near_error_step"], 4)
        self.assertEqual(rows["late"]["steps_before_a"], 2)
        self.assertEqual(rows["late"]["method_a_step"], 6)
        self.assertTrue(rows["late"]["same_step"])  # tautological: B uses A's locator step
        self.assertEqual(rows["early"]["method_b_status"], "empty_window")
        self.assertIsNone(rows["early"]["earliest_near_error_step"])
        self.assertIsNone(rows["early"]["steps_before_a"])
        root = Path(agr.__file__).parent
        for name in ("earliest_near_error_step", "steps_before_a"):
            self.assertIn(name, (root / "CREDIT_ASSIGNMENT.md").read_text())
            self.assertIn(name, (root / "RUNNER_TABLES.md").read_text())
        self.assertIn("tautological", (root / "CREDIT_ASSIGNMENT.md").read_text().lower())
        self.assertIn("tautological", (root / "RUNNER_TABLES.md").read_text().lower())

    def test_undrawn_admitted_failure_is_absent_and_a_missing_draw_fails(self):
        drawn = [step(1, call("bash", "ok")), step(2, call("bash", "error: boom"))]
        undrawn = [step(1, call("bash", "ok")), step(2, call("bash", "ok")), step(3, call("bash", "error: late"))]
        judge = FakeJudge()
        run = _run({"drawn": drawn, "undrawn": undrawn}, drawn=["drawn"], judge=judge)
        # Both failures have a window. Only the drawn one is judged.
        self.assertEqual(len(judge.prompts), 1)
        b_ids = [row["trial_id"] for row in json.loads("[" + ",".join((run / "credit_b.jsonl").read_text().splitlines()) + "]")]
        self.assertEqual(b_ids, ["drawn"])
        rows = agr.run_agreement(run)
        self.assertEqual([row["trial_id"] for row in rows], ["drawn"])
        self.assertNotIn("undrawn", {row["trial_id"] for row in rows})
        self.assertTrue(all(row["drawn"] for row in rows))
        # Method A still scored the undrawn failure. The agreement table does not.
        a_ids = {row["trial_id"] for row in json.loads("[" + ",".join((run / "credit_a.jsonl").read_text().splitlines()) + "]")}
        self.assertEqual(a_ids, {"drawn", "undrawn"})
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(agr.main(["--run", str(run)]), 0)
        summary = json.loads(buf.getvalue())
        self.assertEqual((summary["rows"], summary["drawn"], summary["probe_errors"]), (1, 1, 1))
        # The undrawn failure is also a probe (step 3). It is not in the count.

        (run / "credit_draw.json").unlink()
        with self.assertRaisesRegex(ValueError, "credit_draw.json is missing"):
            agr.run_agreement(run)
        with self.assertRaisesRegex(ValueError, "credit_draw.json is missing"):
            credit_b.run_method_b(run, FakeJudge())


if __name__ == "__main__":
    unittest.main()
