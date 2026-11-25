"""SEA-110: ideation proposals, the allowed change surface, and the success rule. Fake ideator; offline."""

from __future__ import annotations

import inspect
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
        self._install_fresh_baseline()

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

    def _install_fresh_baseline(self):
        """Copy the pilot summary's counts into the fresh-baseline manifest.

        Later tests overwrite the fresh row. The summary row stays where the
        runner wrote it, so a test can show evaluate ignores it.
        """
        doc = {}
        for summary in rn.read_rows(self.run / "summary.jsonl"):
            if summary.get("patch_id") is not None:
                continue
            cell = f"{summary['model']}/{summary['task']}"
            doc[cell] = {
                "schema": "openbench.reflection.credit_baseline/v1", "cell": cell,
                "task": summary["task"], "model": summary["model"], "passes": summary["passes"],
                "completed": summary["completed"], "set_aside": summary.get("set_aside", 0),
                "provider_blocked": summary.get("provider_blocked", 0),
                "model_refused": summary.get("model_refused", 0),
                "baseline_commit": "installed-for-test",
                "image": {"ref": "recorded:test", "id": "sha256:" + "11" * 32},
                "image_matches_pin": True,
            }
        (self.run / "credit_baseline.json").write_text(json.dumps(doc) + "\n", encoding="utf-8")

    def _fresh(self, proposal):
        return json.loads((self.run / "credit_baseline.json").read_text(encoding="utf-8"))[
            f"{proposal['model']}/{proposal['task']}"]

    def _set_baseline(self, proposal, **fields):
        doc = json.loads((self.run / "credit_baseline.json").read_text(encoding="utf-8"))
        doc[f"{proposal['model']}/{proposal['task']}"].update(fields)
        (self.run / "credit_baseline.json").write_text(json.dumps(doc) + "\n", encoding="utf-8")

    def _set_summary(self, proposal, **fields):
        rows = rn.read_rows(self.run / "summary.jsonl")
        for r in rows:
            if r["task"] == proposal["task"] and r["model"] == proposal["model"] and r["patch_id"] is None:
                r.update(fields)
        (self.run / "summary.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    def test_set_aside_cap_admits_up_to_three_and_the_setting_overrides_it(self):
        proposal = self.proposal()
        self._set_baseline(proposal, set_aside=3, provider_blocked=3, model_refused=0)
        admitted = self.arms(select=0, confirm=0, confirm_baseline=0)
        idn.evaluate(self.run, proposal, admitted)
        self.assertEqual(len(admitted.calls), 30)  # the cell entered selection

        for n in (4, 5):
            self._set_baseline(proposal, set_aside=n)
            blocked = self.arms(select=0, confirm=0, confirm_baseline=0)
            with self.assertRaisesRegex(ValueError, f"{n} set-aside"):
                idn.evaluate(self.run, proposal, blocked)
            self.assertEqual(blocked.calls, [])

        self._set_baseline(proposal, set_aside=1)
        tightened = self.arms(select=0, confirm=0, confirm_baseline=0)
        with self.assertRaisesRegex(ValueError, "max_set_aside 0"):
            idn.evaluate(self.run, proposal, tightened, max_set_aside=0)
        self.assertEqual(tightened.calls, [])

        doc = json.loads((self.run / "credit_baseline.json").read_text(encoding="utf-8"))
        row = doc[f"{proposal['model']}/{proposal['task']}"]
        row.pop("set_aside", None)
        row.update(provider_blocked=1, model_refused=3)
        (self.run / "credit_baseline.json").write_text(json.dumps(doc) + "\n", encoding="utf-8")
        # The pilot summary still has no set-aside. The cap reads the fresh baseline.
        split = self.arms(select=0, confirm=0, confirm_baseline=0)
        with self.assertRaisesRegex(ValueError, "4 set-aside"):
            idn.evaluate(self.run, proposal, split)
        self.assertEqual(split.calls, [])

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

    def test_selection_uses_the_fresh_baseline_not_the_old_summary(self):
        proposal = self.proposal()
        # Old pilot summary would admit 12/30. The fresh baseline is 15/30, so 12 is not a candidate.
        self._set_summary(proposal, passes=10, completed=30)
        self._set_baseline(proposal, passes=15, completed=30, set_aside=0)
        short = self.arms(select=12, confirm=30, confirm_baseline=0)
        row = idn.evaluate(self.run, proposal, short)
        self.assertEqual(len(short.calls), 30)
        self.assertEqual((row["selection_baseline_passes"], row["selection_alt_passes"], row["candidate"]), (15, 12, False))
        self.assertIsNone(row["confirmation_alt_passes"])
        self.assertFalse(row["success"])

        # A second proposal id, so this arm is a new run and not a resume of the 12/30 arm.
        tie_proposal = dict(proposal, proposal_id=proposal["proposal_id"] + "-tie")
        tied = self.arms(select=15, confirm=30, confirm_baseline=0)
        tie = idn.evaluate(self.run, tie_proposal, tied)
        self.assertEqual(len(tied.calls), 30)
        self.assertEqual((tie["selection_baseline_passes"], tie["selection_alt_passes"], tie["candidate"]), (15, 15, False))
        self.assertFalse(tie["selection_beats_baseline"])

    def test_one_more_pass_than_the_fresh_baseline_is_a_candidate_when_fisher_p_exceeds_point_ten(self):
        proposal = self.proposal()
        self._set_summary(proposal, passes=10, completed=30)
        self._set_baseline(proposal, passes=15, completed=30, set_aside=0)
        executor = self.arms(select=16, confirm=16, confirm_baseline=14)
        row = idn.evaluate(self.run, proposal, executor)
        fisher = idn.fisher_one_sided(16, 30, 15, 30)
        self.assertGreater(fisher, 0.10)
        self.assertEqual(idn.ALPHA, 1.0)
        self.assertEqual(row["selection_fisher_p"], round(fisher, 6))
        self.assertGreater(row["selection_fisher_p"], 0.10)
        self.assertEqual((row["selection_baseline_passes"], row["selection_alt_passes"], row["candidate"]), (15, 16, True))
        # Confirmation is a new baseline (14), not the selection baseline (15) and not the old summary (10).
        self.assertEqual((row["confirmation_baseline_passes"], row["confirmation_alt_passes"], row["confirmed"], row["success"]),
                         (14, 16, True, True))
        self.assertGreater(row["confirmation_fisher_p"], 0.10)

    def test_missing_fresh_baseline_raises_and_does_not_read_the_summary(self):
        proposal = self.proposal()
        self._set_summary(proposal, passes=0, completed=30)
        (self.run / "credit_baseline.json").unlink()
        executor = self.arms(select=1, confirm=30, confirm_baseline=0)
        with self.assertRaisesRegex(ValueError, "fresh baseline"):
            idn.evaluate(self.run, proposal, executor)
        self.assertEqual(executor.calls, [])
        with self.assertRaisesRegex(ValueError, "retired"):
            idn.summary_row_baseline(self.run, proposal)

    def test_result_records_alpha_and_baseline_commit_and_refuses_any_other_alpha(self):
        proposal = self.proposal()
        self._set_baseline(proposal, baseline_commit="fresh-commit", passes=0, completed=30, set_aside=0)
        row = idn.evaluate(self.run, proposal, self.arms(select=1, confirm=0, confirm_baseline=0))
        self.assertEqual(row["alpha"], 1.0)
        self.assertEqual(row["baseline_commit"], "fresh-commit")
        self.assertEqual(idn.ALPHA, 1.0)
        self.assertNotIn("alpha", inspect.signature(idn.evaluate).parameters)
        self.assertIn("alpha", inspect.signature(idn.decide).parameters)
        # decide() still accepts an explicit alpha. evaluate() does not, and will not record one.
        gated = idn.decide({"passes": 0, "completed": 30}, {"passes": 1, "completed": 30}, alpha=0.05)
        self.assertEqual((gated["beats_baseline"], gated["success"], gated["alpha"]), (True, False, 0.05))

        saved = (self.run / "ideation_results.jsonl").read_text(encoding="utf-8")
        other = dict(proposal, proposal_id=proposal["proposal_id"] + "-alpha")
        with mock_patch.object(idn, "ALPHA", 0.05):
            with self.assertRaisesRegex(ValueError, "alpha"):
                idn.evaluate(self.run, other, self.arms(select=1, confirm=1, confirm_baseline=0))
        self.assertEqual((self.run / "ideation_results.jsonl").read_text(encoding="utf-8"), saved)

    def test_every_arm_reuses_the_recorded_image_and_a_mismatch_is_refused(self):
        from obench.reflection import credit_baseline as base
        recorded = {
            "ref": "openbench-tb2-query-optimize:pinned",
            "id": "sha256:968acc7b8b359d34b367e04464cfc78d6d32c5ad000182d52dc5793e2cb74945",
            "matches_pin": False,
        }
        rows = rn.read_rows(self.run / "trials.jsonl")
        for row in rows:
            row.update(image_ref=recorded["ref"], image_id=recorded["id"], image_matches_pin=False)
        (self.run / "trials.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

        class Echo(rn.FixtureExecutor):
            """Reports the image the arm was given, so a re-pin shows up on the trial row."""

            def __init__(self, bad_id=None):
                super().__init__({})
                self.bad_id = bad_id
                self.smoke_compaction = True
                self.seen_smoke = []

            def run_trial(self, spec, run_dir):
                self.seen_smoke.append(self.smoke_compaction)
                rid = spec.run_id
                unpatched = "--baseline--" in rid or "--confirm-baseline--" in rid
                self.passes = {(spec.task, spec.model): 0 if unpatched else 99}
                result = super().run_trial(spec, run_dir)
                image = dict(spec.recorded_image)
                if self.bad_id:
                    image["id"] = self.bad_id
                result.image = image
                return result

        echo = Echo()
        manifests = base.run_baselines(self.run, [f"{OPUS}/extract-elf"], echo, n_trials=2)
        fresh = manifests[f"{OPUS}/extract-elf"]
        self.assertIs(fresh["image_matches_pin"], False)
        self.assertIs(fresh["image_matches_pin_false"], True)
        self.assertEqual(fresh["image"]["id"], recorded["id"])

        proposal = self.proposal()
        row = idn.evaluate(self.run, proposal, echo, n_trials=2)
        self.assertTrue(row["candidate"] and row["success"])
        self.assertEqual(row["alpha"], 1.0)
        self.assertTrue(echo.seen_smoke)
        self.assertTrue(all(flag is False for flag in echo.seen_smoke))

        def image_ids(path):
            return {item.get("image_id") for item in rn.read_rows(path)}

        arms = {
            "fresh baseline": self.run / fresh["run_dir"] / "trials.jsonl",
            "select": self.run / row["selection_run_dir"] / "trials.jsonl",
            "confirm": self.run / row["confirmation_run_dirs"][0] / "trials.jsonl",
            "confirm-baseline": self.run / row["confirmation_run_dirs"][1] / "trials.jsonl",
        }
        for name, path in arms.items():
            self.assertEqual(image_ids(path), {recorded["id"]}, name)
            plan = json.loads((path.parent / "plan.json").read_text(encoding="utf-8"))
            self.assertFalse(plan["config"]["smoke_compaction"])
            self.assertEqual(plan["config"]["recorded_image"]["id"], recorded["id"])
            self.assertIs(plan["config"]["recorded_image"]["matches_pin"], False)
        self.assertTrue(all(spec.recorded_image["id"] == recorded["id"] and spec.recorded_image["matches_pin"] is False
                            for spec in echo.calls))

        saved = (self.run / "ideation_results.jsonl").read_text(encoding="utf-8")
        mismatch = dict(proposal, proposal_id=proposal["proposal_id"] + "-mismatch")
        with self.assertRaisesRegex(base.BaselineError, "refusing to re-pin"):
            idn.evaluate(self.run, mismatch, Echo(bad_id="sha256:" + "ff" * 32), n_trials=2)
        self.assertEqual((self.run / "ideation_results.jsonl").read_text(encoding="utf-8"), saved)

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
        self._install_fresh_baseline()


class Estimate(unittest.TestCase):
    def test_confirmation_is_in_the_cost_estimate(self):
        est = rn.ideation_estimate(rn.FixtureExecutor({}, cost_per_trial=2.0), {OPUS: 1})
        self.assertEqual((est["selection_usd"], est["confirmation_usd"], est["total_usd"]), (300.0, 600.0, 900.0))
        half = rn.ideation_estimate(rn.FixtureExecutor({}, cost_per_trial=2.0), {OPUS: 1}, candidate_fraction=0.2)
        self.assertEqual(half["confirmation_usd"], 120.0)


if __name__ == "__main__":
    unittest.main()
