"""SEA-109: credit-assignment Method B (System 1 weights). A fake judge; no model calls."""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from obench.reflection import credit_b as cb
from obench.tests.test_reflection_credit_a import CLEAR_ERROR, RECOVERY, step, call


class FakeJudge:
    model_id = "fake-system1"

    def __init__(self, labels=None, raw=None, raises=None):
        self.labels, self.raw, self.raises, self.prompts = labels or {}, raw, raises, []

    def judge(self, prompt):
        self.prompts.append(prompt)
        if self.raises:
            raise self.raises
        if self.raw is not None:
            return self.raw, None
        payload = json.loads(prompt[prompt.index("{\n"):])
        out = [{"step": s["step"], "label": self.labels.get(s["step"], "correct"), "reason": "r"}
               for s in payload["earlier_steps"]]
        return json.dumps({"labels": out}), {"promptTokenCount": 10}


SIX = [step(1, call("bash", "ok")), step(2, call("bash", "ok")), step(3, call("bash", "ok")),
       step(4, call("bash", "ok")), step(5, call("bash", "error: boom")), step(6, call("bash", "fixed"))]


class Weights(unittest.TestCase):
    def test_one_before_window_partial_near_error_zero_past_cutoff(self):
        row = cb.method_b_row({"trial_id": "t", "task": "x", "model": "m"}, SIX, FakeJudge({4: "near_error"}),
                              cb.MethodBConfig.from_dict({"k": 2}))
        self.assertEqual(row["first_failing_step"], 5)
        self.assertEqual(row["window"], [3, 4])
        self.assertEqual([(w["step"], w["weight"], w["why"]) for w in row["weights"]],
                         [(1, 1.0, "before_window"), (2, 1.0, "before_window"), (3, 1.0, "correct"),
                          (4, 0.5, "near_error"), (5, 0.0, "past_cutoff"), (6, 0.0, "past_cutoff")])
        self.assertEqual(row["labels"], {"3": "correct", "4": "near_error"})

    def test_default_k_is_4(self):
        row = cb.method_b_row({"trial_id": "t", "task": "x", "model": "m"}, SIX, FakeJudge({1: "near_error"}),
                              cb.MethodBConfig())
        self.assertEqual((row["k"], row["window"]), (4, [1, 2, 3, 4]))
        self.assertEqual([w["weight"] for w in row["weights"]], [0.5, 1.0, 1.0, 1.0, 0.0, 0.0])

    def test_k_and_partial_weight_come_from_config(self):
        cfg = cb.MethodBConfig.from_dict({"k": 3, "near_error_weight": 0.25})
        row = cb.method_b_row({"trial_id": "t", "task": "x", "model": "m"}, SIX, FakeJudge({2: "near_error", 4: "near_error"}), cfg)
        self.assertEqual(row["window"], [2, 3, 4])
        self.assertEqual([w["weight"] for w in row["weights"]], [1.0, 0.25, 1.0, 0.25, 0.0, 0.0])
        self.assertEqual((row["k"], row["near_error_weight"]), (3, 0.25))
        self.assertEqual((cb.K, cb.NEAR_ERROR_WEIGHT, cb.SYSTEM1_MODEL), (4, 0.5, "gemini-3.8-flash"))

    def test_same_first_failure_as_method_a(self):
        from obench.reflection.credit_locator import first_failure
        for trace in (CLEAR_ERROR, RECOVERY, SIX):
            row = cb.method_b_row({"trial_id": "t", "task": "x", "model": "m"}, trace, FakeJudge(), cb.MethodBConfig())
            self.assertEqual(row["first_failing_step"], first_failure(trace).step)

    def test_first_step_failure_needs_no_judge_and_empty_trace_is_recorded(self):
        judge = FakeJudge()
        row = cb.method_b_row({"trial_id": "t", "task": "x", "model": "m"},
                              [step(1, call("bash", "Traceback (most recent call last):"))], judge, cb.MethodBConfig())
        self.assertEqual((row["window"], judge.prompts), ([], []))
        self.assertEqual(row["weights"], [{"step": 1, "weight": 0.0, "why": "past_cutoff"}])
        empty = cb.method_b_row({"trial_id": "t", "task": "x", "model": "m"}, [], judge, cb.MethodBConfig())
        self.assertEqual((empty["judge_error"], empty["weights"]), ("empty_trace", None))

    def test_bad_judge_output_is_auditable_not_silent(self):
        for judge, msg in ((FakeJudge(raw="not json"), "unparseable"),
                           (FakeJudge(raw=json.dumps({"labels": [{"step": 3, "label": "maybe"}]})), "unparseable"),
                           (FakeJudge(raw=json.dumps({"labels": [{"step": 4, "label": "correct"}]})), "unparseable"),
                           (FakeJudge(raises=TimeoutError("slow")), "TimeoutError")):
            row = cb.method_b_row({"trial_id": "t", "task": "x", "model": "m"}, SIX, judge, cb.MethodBConfig())
            self.assertIn(msg, row["judge_error"])
            self.assertIsNone(row["weights"])

    def test_prompt_is_deterministic_and_versioned(self):
        a, b = FakeJudge(), FakeJudge()
        for judge in (a, b):
            cb.method_b_row({"trial_id": "t", "task": "x", "model": "m"}, SIX, judge, cb.MethodBConfig())
        self.assertEqual(a.prompts, b.prompts)
        self.assertEqual(cb.PROMPT_VERSION, "B1")

    def test_config_validation(self):
        for raw in ({"k": -1}, {"near_error_weight": 1.5}, {"cutoff_rule": "other"}, {"system1_thinking": {}}, {"x": 1}):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                cb.MethodBConfig.from_dict(raw)


class Table(unittest.TestCase):
    def test_own_table_beside_method_a(self):
        from obench.tests.test_reflection_credit_a import MethodA
        run = MethodA().make_run()
        from obench.reflection import credit_a
        a_rows = credit_a.run_method_a(run)
        a_text = (run / "credit_a.jsonl").read_text()
        rows = cb.run_method_b(run, FakeJudge())
        self.assertEqual([r["trial_id"] for r in rows], [r["trial_id"] for r in a_rows])
        self.assertEqual((run / "credit_a.jsonl").read_text(), a_text)  # Method A's table untouched
        self.assertEqual(sorted(p.name for p in run.glob("*.jsonl")), ["credit_a.jsonl", "credit_b.jsonl", "trials.jsonl"])
        self.assertTrue(all(r["schema"] == cb.METHOD_B_SCHEMA for r in rows))

    def test_documented_fields_match_rows(self):
        doc = Path(cb.__file__).with_name("CREDIT_ASSIGNMENT.md").read_text()
        section = doc.split("### Table (`credit_b.jsonl`", 1)[1].split("\n## ", 1)[0]
        documented = {n for line in re.findall(r"^\| ([^|]+) \|", section, re.M) for n in re.findall(r"`([a-z_0-9]+)`", line)}
        row = cb.method_b_row({"trial_id": "t", "task": "x", "model": "m"}, SIX, FakeJudge(), cb.MethodBConfig())
        self.assertLessEqual(set(row) - {"schema"}, documented)


class VertexJudge(unittest.TestCase):
    def test_request_sets_thinking_and_schema_and_reads_text(self):
        seen = {}

        class Resp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self):
                return json.dumps({"candidates": [{"content": {"parts": [
                    {"text": "plan", "thought": True}, {"text": "{\"labels\": []}"}]}}],
                    "usageMetadata": {"thoughtsTokenCount": 7}}).encode()

        def opener(req, timeout):
            seen["url"], seen["body"], seen["auth"] = req.full_url, json.loads(req.data), req.headers["Authorization"]
            return Resp()
        judge = cb.VertexGeminiJudge(cb.MethodBConfig(), "proj", lambda: "tok", opener=opener)
        text, usage = judge.judge("p")
        self.assertEqual((text, usage), ('{"labels": []}', {"thoughtsTokenCount": 7}))
        self.assertTrue(seen["url"].endswith("/locations/global/publishers/google/models/gemini-3.8-flash:generateContent"))
        self.assertEqual(seen["body"]["generationConfig"]["thinkingConfig"], {"thinkingLevel": "LOW"})
        self.assertEqual((seen["body"]["generationConfig"]["temperature"], seen["auth"]), (0, "Bearer tok"))


if __name__ == "__main__":
    unittest.main()
