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

    def test_bare_beat_counts_including_one_pass_against_zero(self):
        d = idn.decide(self.s(0), self.s(1))
        self.assertEqual((d["beats_baseline"], d["success"], d["alpha"]), (True, True, 1.0))
        self.assertAlmostEqual(d["fisher_p"], 0.5)  # reported, not gating
        self.assertEqual(d["reason"], "beats baseline at N")
        self.assertEqual(idn.ALPHA, 1.0)

    def test_needs_full_n_on_both_sides(self):
        for base, alt in ((self.s(0), self.s(1, completed=1)), (self.s(0, completed=29), self.s(20))):
            d = idn.decide(base, alt)
            self.assertEqual((d["complete"], d["success"]), (False, False))

    def test_ties_and_regressions_do_not_count(self):
        self.assertTrue(idn.decide(self.s(10), self.s(11))["success"])
        self.assertFalse(idn.decide(self.s(10), self.s(10))["success"])
        self.assertFalse(idn.decide(self.s(12), self.s(9))["success"])
        self.assertIsNotNone(idn.decide(self.s(12), self.s(9))["fisher_p"])  # always recorded

    def test_optional_significance_gate_for_sensitivity_analysis(self):
        d = idn.decide(self.s(0), self.s(1), alpha=0.05)
        self.assertEqual((d["beats_baseline"], d["success"]), (True, False))
        self.assertTrue(idn.decide(self.s(0), self.s(6), alpha=0.05)["success"])

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

    def arms(self, select, confirm, confirm_baseline):
        class Arms(rn.FixtureExecutor):
            def run_trial(self, spec, run_dir):
                arm = ("confirm-baseline" if "--confirm-baseline--" in spec.run_id else
                       "confirm" if "--confirm--" in spec.run_id else "select")
                self.passes = {(spec.task, spec.model): {"select": select, "confirm": confirm,
                                                         "confirm-baseline": confirm_baseline}[arm]}
                return super().run_trial(spec, run_dir)
        return Arms({})

    def proposal(self):
        return idn.propose(self.run, self.trial, "A", FakeIdeator([good(i) for i in range(5)]))[0]

    def test_candidate_confirmed_on_fresh_runs(self):
        proposal, executor = self.proposal(), self.arms(select=3, confirm=5, confirm_baseline=1)
        row = idn.evaluate(self.run, proposal, executor)
        self.assertEqual(len(executor.calls), 90)  # 30 selection + 30 fresh alternative + 30 fresh baseline
        self.assertEqual((row["selection_baseline_passes"], row["selection_alt_passes"], row["candidate"]), (2, 3, True))
        self.assertEqual((row["confirmation_baseline_passes"], row["confirmation_alt_passes"], row["confirmed"], row["success"]),
                         (1, 5, True, True))
        self.assertIsNotNone(row["selection_fisher_p"])
        self.assertIsNotNone(row["confirmation_fisher_p"])
        ids = {}
        for c in executor.calls:
            ids.setdefault(c.run_id.split("--")[1], set()).add(c.trial_id)
        self.assertEqual(sorted(ids), ["confirm", "confirm-baseline", "select"])
        self.assertFalse(ids["select"] & ids["confirm"] or ids["select"] & ids["confirm-baseline"]
                         or ids["confirm"] & ids["confirm-baseline"])  # no trial reused across stages or arms
        baseline_calls = [c for c in executor.calls if "--confirm-baseline--" in c.run_id]
        self.assertTrue(all(c.patch is None and c.patch_id is None for c in baseline_calls))
        patched = [c for c in executor.calls if "--confirm-baseline--" not in c.run_id]
        self.assertTrue(all(c.patch == proposal["patch"] for c in patched))
        self.assertEqual(row["credit_method"], "A")
        self.assertEqual(len(rn.read_rows(self.run / "ideation_results.jsonl")), 1)

    def test_one_pass_against_zero_is_a_candidate_but_must_confirm(self):
        self.setUp_zero_baseline()
        row = idn.evaluate(self.run, self.proposal(), self.arms(select=1, confirm=0, confirm_baseline=0))
        self.assertEqual((row["candidate"], row["confirmed"], row["success"]), (True, False, False))
        self.assertAlmostEqual(row["selection_fisher_p"], 0.5)

    def test_non_candidates_are_not_confirmed(self):
        executor = self.arms(select=2, confirm=30, confirm_baseline=0)
        row = idn.evaluate(self.run, self.proposal(), executor)
        self.assertEqual(len(executor.calls), 30)
        self.assertEqual((row["candidate"], row["confirmed"], row["success"], row["confirmation_alt_passes"]),
                         (False, None, False, None))
        with self.assertRaises(ValueError):
            idn.evaluate(self.run, dict(self.proposal(), status="rejected"), executor)

    def setUp_zero_baseline(self):
        import shutil
        shutil.rmtree(self.run)
        self.run.mkdir()
        cfg = rn.RunConfig.from_dict({"run_id": "base", "suite": "pilot", "models": [OPUS], "n_trials": 30,
                                      "tasks": ["extract-elf"], "max_rounds": 1})
        rn.Runner(cfg, self.run, rn.FixtureExecutor({})).run()
        self.trial = rn.read_rows(self.run / "trials.jsonl")[0]
        from obench.reflection import credit_a
        credit_a.run_method_a(self.run)


class Estimate(unittest.TestCase):
    def test_confirmation_is_in_the_cost_estimate(self):
        est = rn.ideation_estimate(rn.FixtureExecutor({}, cost_per_trial=2.0), {OPUS: 1})
        self.assertEqual((est["selection_usd"], est["confirmation_usd"], est["total_usd"]), (300.0, 600.0, 900.0))
        half = rn.ideation_estimate(rn.FixtureExecutor({}, cost_per_trial=2.0), {OPUS: 1}, candidate_fraction=0.2)
        self.assertEqual(half["confirmation_usd"], 120.0)


if __name__ == "__main__":
    unittest.main()
