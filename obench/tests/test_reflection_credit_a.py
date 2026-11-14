"""SEA-108: first-failure locator and credit-assignment Method A. Synthetic traces only."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from obench.reflection import credit_a as ca
from obench.reflection import credit_locator as loc


def step(n, *calls, text=""):
    return {"step": n, "tool_calls": list(calls), "assistant_text": text}


def call(name, result, status="completed"):
    return {"name": name, "arguments": {}, "result": result, "status": status}


CLEAR_ERROR = [step(1, call("bash", "main.rs\nCargo.toml")),
               step(2, call("bash", "error[E0425]: cannot find value `x` in this scope")),
               step(3, call("edit", "ok")), step(4, text="Done.")]
RECOVERY = [step(1, call("bash", "ok")),
            step(2, call("bash", "Traceback (most recent call last):\n  File \"a.py\"\nNameError: y")),
            step(3, call("edit", "patched")),
            step(4, call("bash", "4 passed")),
            step(5, call("bash", "FAILED test_edge.py::test_empty")), step(6, text="All good.")]
SILENT = [step(1, call("bash", "ok")), step(2, call("write", "wrote out.txt")), step(3, text="Finished; output in out.txt")]
STATUS_ERROR = [step(1, call("bash", "ok")), step(2, call("bash", "permission denied", status="error"))]


class Locator(unittest.TestCase):
    def test_clear_first_error(self):
        f = loc.first_failure(CLEAR_ERROR)
        self.assertEqual((f.step, f.signal, f.tool), (2, "tool_error_output", "bash"))
        self.assertIn("error[E0425]", f.evidence)

    def test_error_then_recovery_still_flags_the_first_causing_step(self):
        f = loc.first_failure(RECOVERY)
        self.assertEqual((f.step, f.signal), (2, "tool_error_output"))  # not step 5
        self.assertIn("Traceback", f.evidence)

    def test_errored_status_and_silent_failure(self):
        self.assertEqual(loc.first_failure(STATUS_ERROR).signal, "tool_error_status")
        f = loc.first_failure(SILENT)
        self.assertEqual((f.step, f.signal), (3, "final_answer_rejected"))

    def test_empty_trace(self):
        f = loc.first_failure([])
        self.assertEqual((f.step, f.signal, f.steps_total), (None, "empty_trace", 0))

    def test_benign_outputs_are_not_errors(self):
        for text in ("exit 0", "0 errors, 3 warnings", "error handling added to parse()", "12 passed"):
            with self.subTest(text=text):
                self.assertIsNone(loc.step_error(step(1, call("bash", text))))

    def test_steps_are_ordered_by_step_index(self):
        self.assertEqual(loc.first_failure(list(reversed(CLEAR_ERROR))).step, 2)


class MethodA(unittest.TestCase):
    def make_run(self):
        run = Path(tempfile.mkdtemp())
        trials = []
        for i, (trace, passed, status) in enumerate([(CLEAR_ERROR, False, "completed"), (RECOVERY, False, "completed"),
                                                      ([], False, "completed"), (SILENT, True, "completed"),
                                                      (CLEAR_ERROR, None, "error")]):
            rel = f"trials/m/t/{i}/trace.jsonl"
            (run / rel).parent.mkdir(parents=True)
            (run / rel).write_text("".join(json.dumps(s) + "\n" for s in trace))
            trials.append({"run_id": "r", "trial_id": f"t{i}", "task": "t", "model": "claude-opus-5-5",
                           "patch_id": None, "status": status, "passed": passed, "trace": rel})
        (run / "trials.jsonl").write_text("".join(json.dumps(t) + "\n" for t in trials))
        return run

    def test_own_table_for_failed_trials_only(self):
        run = self.make_run()
        before = (run / "trials.jsonl").read_text()
        rows = ca.run_method_a(run)
        self.assertEqual([r["trial_id"] for r in rows], ["t0", "t1", "t2"])  # passed and errored trials excluded
        self.assertEqual([r["failing_step"] for r in rows], [2, 2, None])
        self.assertEqual(rows[2]["signal"], "empty_trace")
        self.assertEqual(rows[0]["trace_step"], "trials/m/t/0/trace.jsonl#step=2")
        self.assertTrue(all(r["rule_version"] == "A1+locator-v1" for r in rows))
        self.assertEqual((run / "trials.jsonl").read_text(), before)  # raw table untouched
        self.assertEqual(sorted(p.name for p in run.glob("*.jsonl")), ["credit_a.jsonl", "trials.jsonl"])
        on_disk = [json.loads(l) for l in (run / "credit_a.jsonl").read_text().splitlines()]
        self.assertEqual(on_disk, rows)
        self.assertEqual(ca.run_method_a(run), rows)  # idempotent

    def test_documented_fields_match_rows(self):
        import re
        doc = Path(ca.__file__).with_name("CREDIT_ASSIGNMENT.md").read_text()
        section = doc.split("## Method A", 1)[1].split("\n## ", 1)[0]
        documented = {n for line in re.findall(r"^\| ([^|]+) \|", section, re.M) for n in re.findall(r"`([a-z_]+)`", line)}
        row = ca.method_a_row({"trial_id": "x", "task": "t", "model": "m", "trace": "a"}, CLEAR_ERROR)
        self.assertEqual(set(row) - {"schema"}, documented)


if __name__ == "__main__":
    unittest.main()
