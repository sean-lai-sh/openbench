"""SEA-110: ideation proposals, the allowed change surface, and the success rule. Fake ideator; offline."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch as mock_patch

from obench.hardsuite import config as hs_config
from obench.reflection import ideation as idn
from obench.reflection import patches as pt
from obench.reflection import runner as rn
from obench.reflection.wire_proxy import WireProxy

OPUS = "claude-opus-5-5"


def good(i):
    return {"rationale": f"r{i}", "patch": {"schema": pt.PATCH_SCHEMA, "ops": [
        {"op": "system_append", "text": f"Run the tests after every edit ({i})."}]}}


class FakeIdeator:
    model_id = "fake-ideator"

    def __init__(self, *answers):
        self.answers, self.prompts = list(answers), []

    def propose(self, prompt):
        self.prompts.append(prompt)
        return json.dumps({"alternatives": self.answers.pop(0)}), {"input_tokens": 1}


class Patches(unittest.TestCase):
    def test_valid_ops(self):
        p = {"schema": pt.PATCH_SCHEMA, "ops": [
            {"op": "system_replace", "find": "a", "replace": ""},
            {"op": "tool_description", "tool": "bash", "description": "Run a shell command."},
            {"op": "tool_param_description", "tool": "bash", "param": "command", "description": "One command."}]}
        self.assertEqual(pt.validate_patch(p), [])

    def test_out_of_surface_is_rejected(self):
        cases = [
            {"schema": pt.PATCH_SCHEMA, "ops": [{"op": "code_patch", "diff": "--- a/agent.py"}]},
            {"schema": pt.PATCH_SCHEMA, "ops": [{"op": "system_append", "text": "x", "file": "agent.py"}]},
            {"schema": pt.PATCH_SCHEMA, "ops": [{"op": "system_append", "text": "x"}], "temperature": 0.2},
            {"schema": pt.PATCH_SCHEMA, "ops": [{"op": "set_model", "model": "claude-sonnet-5-5"}]},
            {"schema": pt.PATCH_SCHEMA, "ops": [{"op": "tool_description", "tool": "bash"}]},
            {"schema": pt.PATCH_SCHEMA, "ops": []},
            {"ops": [{"op": "system_append", "text": "x"}]},
            "rm -rf /",
        ]
        for p in cases:
            with self.subTest(p=p):
                self.assertTrue(pt.validate_patch(p))

    def test_apply_per_wire(self):
        p = {"schema": pt.PATCH_SCHEMA, "ops": [
            {"op": "system_append", "text": "NEW"},
            {"op": "tool_param_description", "tool": "bash", "param": "command", "description": "D"},
            {"op": "tool_description", "tool": "missing", "description": "x"}]}
        anth = {"system": [{"type": "text", "text": "S"}], "tools": [
            {"name": "bash", "input_schema": {"properties": {"command": {"type": "string"}}}}], "messages": []}
        out, log = pt.apply_patch("anthropic", anth, p)
        self.assertEqual(out["system"][-1]["text"], "NEW")
        self.assertEqual(out["tools"][0]["input_schema"]["properties"]["command"]["description"], "D")
        self.assertEqual([l["applied"] for l in log], [True, True, False])
        self.assertNotIn("description", anth["tools"][0]["input_schema"]["properties"]["command"])  # input untouched
        oai = {"messages": [{"role": "system", "content": "S"}], "tools": [{"type": "function", "function": {
            "name": "bash", "parameters": {"properties": {"command": {}}}}}]}
        out, _ = pt.apply_patch("openai_chat", oai, p)
        self.assertEqual(out["messages"][0]["content"], "S\n\nNEW")
        gem = {"contents": [], "tools": [{"functionDeclarations": [{"name": "bash", "parameters": {"properties": {"command": {}}}}]}]}
        out, _ = pt.apply_patch("gemini", gem, p)
        self.assertEqual(out["systemInstruction"]["parts"], [{"text": "NEW"}])
        self.assertEqual(out["tools"][0]["functionDeclarations"][0]["parameters"]["properties"]["command"]["description"], "D")

    def test_proxy_refuses_an_invalid_patch(self):
        with self.assertRaises(pt.PatchError):
            WireProxy("p", Path(tempfile.mkdtemp()) / "w.jsonl", lambda: "t", patch={"ops": []}, patch_id="x")


class Rule(unittest.TestCase):
    def s(self, passes, completed=30):
        return {"passes": passes, "completed": completed}

    def test_single_lucky_pass_never_counts(self):
        d = idn.decide(self.s(0), self.s(1))
        self.assertTrue(d["beats_baseline"])
        self.assertFalse(d["success"])
        self.assertAlmostEqual(d["fisher_p"], 0.5)

    def test_needs_full_n_on_both_sides(self):
        for base, alt in ((self.s(0), self.s(1, completed=1)), (self.s(0, completed=29), self.s(20))):
            d = idn.decide(base, alt)
            self.assertEqual((d["complete"], d["success"]), (False, False))

    def test_real_improvement_counts_and_ties_do_not(self):
        self.assertTrue(idn.decide(self.s(0), self.s(6))["success"])
        self.assertTrue(idn.decide(self.s(10), self.s(20))["success"])
        self.assertFalse(idn.decide(self.s(10), self.s(10))["beats_baseline"])
        self.assertFalse(idn.decide(self.s(12), self.s(9))["success"])

    def test_fisher(self):
        self.assertAlmostEqual(idn.fisher_one_sided(30, 30, 0, 30), 1 / 118264581564861424, places=25)
        self.assertAlmostEqual(idn.fisher_one_sided(0, 30, 5, 30), 1.0)


class EndToEnd(unittest.TestCase):
    def setUp(self):
        p = mock_patch.dict(os.environ, {hs_config.CUTOFF_ENV: ""})
        p.start()
        self.addCleanup(p.stop)
        self.run = Path(tempfile.mkdtemp())
        cfg = rn.RunConfig.from_dict({"run_id": "base", "suite": "pilot", "models": [OPUS], "n_trials": 30,
                                      "tasks": ["extract-elf"], "max_rounds": 1})
        rn.Runner(cfg, self.run, rn.FixtureExecutor({("extract-elf", OPUS): 2})).run()
        failed = [r for r in rn.read_rows(self.run / "trials.jsonl") if r["passed"] is False]
        self.trial = failed[0]
        from obench.reflection import credit_a
        credit_a.run_method_a(self.run)

    def test_exactly_five_with_credit_method_recorded(self):
        ideator = FakeIdeator([good(i) for i in range(5)])
        rows = idn.propose(self.run, self.trial, "A", ideator)
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(r["status"] == "accepted" and r["credit_method"] == "A" for r in rows))
        self.assertEqual(rows[0]["credit_rows"], {"A": f"credit_a.jsonl#{self.trial['trial_id']}"})
        self.assertEqual(rows[0]["parent_trial_id"], self.trial["trial_id"])
        self.assertEqual(len(rn.read_rows(self.run / "ideation.jsonl")), 5)
        with self.assertRaises(ValueError):  # Method B table absent for this trial
            idn.propose(self.run, self.trial, "A+B", FakeIdeator([good(i) for i in range(5)]))

    def test_out_of_surface_or_wrong_count_reasks_then_rejects(self):
        bad = good(9)
        bad["patch"]["ops"][0]["file"] = "opencode/src/agent.ts"
        ideator = FakeIdeator([good(0), good(1)], [good(i) for i in range(4)] + [bad])
        rows = idn.propose(self.run, self.trial, "A", ideator)
        self.assertEqual(len(ideator.prompts), 2)
        self.assertIn("previous answer was rejected", ideator.prompts[1])
        self.assertEqual([r["status"] for r in rows], ["accepted"] * 4 + ["rejected"])
        self.assertIn("fields", rows[4]["rejection_reasons"][0])
        self.assertIsNone(rows[4]["proposal_id"])

    def test_evaluate_runs_n30_with_the_patch_and_decides(self):
        rows = idn.propose(self.run, self.trial, "A", FakeIdeator([good(i) for i in range(5)]))
        executor = rn.FixtureExecutor({("extract-elf", OPUS): 12})
        result = idn.evaluate(self.run, rows[0], executor)
        self.assertEqual(len(executor.calls), 30)
        self.assertTrue(all(c.patch == rows[0]["patch"] and c.patch_id == rows[0]["proposal_id"] for c in executor.calls))
        self.assertEqual((result["baseline_passes"], result["alt_passes"], result["alt_completed"]), (2, 12, 30))
        self.assertTrue(result["success"])
        self.assertEqual(result["credit_method"], "A")
        self.assertEqual(len(rn.read_rows(self.run / "ideation_results.jsonl")), 1)
        with self.assertRaises(ValueError):
            idn.evaluate(self.run, dict(rows[0], status="rejected"), executor)


if __name__ == "__main__":
    unittest.main()
