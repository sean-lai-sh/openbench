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


def set_aside_run() -> Path:
    """One completed failure per cell, plus the set-aside trials listed for that cell.

    ``four`` mixes both set-aside statuses. ``timeouts`` is five infrastructure
    timeouts, which stay outside the set-aside count.
    """
    run = Path(tempfile.mkdtemp())
    aside = {
        "zero": [],
        "one": ["provider_blocked"],
        "three": ["model_refused", "model_refused", "model_refused"],
        "four": ["provider_blocked", "provider_blocked", "model_refused", "model_refused"],
        "five": ["provider_blocked"] * 5,
        "timeouts": ["timeout"] * 5,
    }
    trials = []
    for task, statuses in aside.items():
        trials.append({"run_id": "r", "trial_id": f"{task}-fail", "task": task, "model": "m",
                       "patch_id": None, "status": "completed", "passed": False, "trace": None})
        for i, status in enumerate(statuses):
            trials.append({"run_id": "r", "trial_id": f"{task}-aside-{i}", "task": task, "model": "m",
                           "patch_id": None, "status": status, "passed": None, "trace": None})
    (run / "trials.jsonl").write_text("".join(json.dumps(t) + "\n" for t in trials))
    return run


def _counts(rows: list[dict]) -> dict[str, int]:
    return {r["task"]: r["set_aside_count"] for r in rows}


class SetAsideCap(unittest.TestCase):
    def test_zero_one_and_three_enter_four_and_five_stay_out(self):
        run = set_aside_run()
        rows = ca.run_method_a(run)
        on_disk = [json.loads(line) for line in (run / "credit_a.jsonl").read_text().splitlines()]
        self.assertEqual(on_disk, rows)
        self.assertEqual(_counts(rows), {"zero": 0, "one": 1, "three": 3, "timeouts": 0})
        self.assertTrue(all(r["max_set_aside"] == 3 for r in rows))

    def test_setting_overrides_the_default(self):
        run = set_aside_run()
        rows = ca.run_method_a(run, max_set_aside=4)
        self.assertEqual(_counts(rows), {"zero": 0, "one": 1, "three": 3, "four": 4, "timeouts": 0})
        self.assertTrue(all(r["max_set_aside"] == 4 for r in rows))
        self.assertEqual(next(r["set_aside_count"] for r in rows if r["task"] == "four"), 4)

        self.assertEqual(ca.main(["--run", str(run), "--max-set-aside", "0"]), 0)
        cli_rows = [json.loads(line) for line in (run / "credit_a.jsonl").read_text().splitlines()]
        self.assertEqual(_counts(cli_rows), {"zero": 0, "timeouts": 0})
        self.assertTrue(all(r["max_set_aside"] == 0 for r in cli_rows))

        self.assertEqual(ca.main(["--run", str(run), "--max-set-aside", "5"]), 0)
        wide = [json.loads(line) for line in (run / "credit_a.jsonl").read_text().splitlines()]
        self.assertEqual(_counts(wide),
                         {"zero": 0, "one": 1, "three": 3, "four": 4, "five": 5, "timeouts": 0})
        self.assertTrue(all(r["max_set_aside"] == 5 for r in wide))

    def test_method_b_config_and_cli_override_report_the_same_count(self):
        from obench.reflection import credit_b as cb
        from obench.tests.test_reflection_credit_b import FakeJudge

        run = set_aside_run()
        rows = cb.run_method_b(run, FakeJudge(), cb.MethodBConfig())
        self.assertEqual(_counts(rows), {"zero": 0, "one": 1, "three": 3, "timeouts": 0})
        self.assertTrue(all(r["max_set_aside"] == 3 for r in rows))

        cfg_path = run / "b.json"
        cfg_path.write_text(json.dumps({"max_set_aside": 0}))
        cfg = cb.resolve_config(cfg_path, max_set_aside=4)
        rows = cb.run_method_b(run, FakeJudge(), cfg)
        on_disk = [json.loads(line) for line in (run / "credit_b.jsonl").read_text().splitlines()]
        self.assertEqual(_counts(on_disk), {"zero": 0, "one": 1, "three": 3, "four": 4, "timeouts": 0})
        self.assertTrue(all(r["max_set_aside"] == 4 for r in on_disk))
        self.assertEqual(cb.MethodBConfig().max_set_aside, 3)


if __name__ == "__main__":
    unittest.main()
