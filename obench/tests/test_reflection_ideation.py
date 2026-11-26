"""SEA-110: ideation proposals, the allowed change surface, and the success rule. Fake ideator; offline."""

from __future__ import annotations

import importlib.util
import inspect
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
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
            commit = rn.code_commit()["commit"]
            doc[cell] = {
                "schema": "openbench.reflection.credit_baseline/v1", "cell": cell,
                "task": summary["task"], "model": summary["model"], "passes": summary["passes"],
                "completed": summary["completed"], "set_aside": summary.get("set_aside", 0),
                "provider_blocked": summary.get("provider_blocked", 0),
                "model_refused": summary.get("model_refused", 0),
                "baseline_commit": commit, "code_commit": commit,
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
        self._set_baseline(proposal, baseline_commit="fresh-commit", code_commit="fresh-commit",
                           passes=0, completed=30, set_aside=0)
        fake = {"commit": "fresh-commit", "branch": "main", "dirty": False}
        with mock_patch("obench.reflection.runner.code_commit", return_value=fake):
            row = idn.evaluate(self.run, proposal, self.arms(select=1, confirm=0, confirm_baseline=0))
        self.assertEqual(row["alpha"], 1.0)
        self.assertEqual(row["baseline_commit"], "fresh-commit")
        self.assertEqual(row["code_commit"], "fresh-commit")
        self.assertEqual(row["selection_code_commit"], "fresh-commit")
        self.assertEqual(row["confirmation_code_commit"], "fresh-commit")
        self.assertEqual(row["confirmation_baseline_code_commit"], "fresh-commit")
        self.assertEqual(idn.ALPHA, 1.0)
        self.assertNotIn("alpha", inspect.signature(idn.evaluate).parameters)
        self.assertIn("alpha", inspect.signature(idn.decide).parameters)
        # decide() still accepts an explicit alpha. evaluate() does not, and will not record one.
        gated = idn.decide({"passes": 0, "completed": 30}, {"passes": 1, "completed": 30}, alpha=0.05)
        self.assertEqual((gated["beats_baseline"], gated["success"], gated["alpha"]), (True, False, 0.05))

        saved = (self.run / "ideation_results.jsonl").read_text(encoding="utf-8")
        other = dict(proposal, proposal_id=proposal["proposal_id"] + "-alpha")
        with mock_patch("obench.reflection.runner.code_commit", return_value=fake), mock_patch.object(idn, "ALPHA", 0.05):
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
        self.assertEqual(fresh["code_commit"], fresh["baseline_commit"])
        for name, path in arms.items():
            self.assertEqual(image_ids(path), {recorded["id"]}, name)
            summary = rn.read_rows(path.parent / "summary.jsonl")[0]
            self.assertEqual(summary["code_commit"], fresh["baseline_commit"], name)
            plan = json.loads((path.parent / "plan.json").read_text(encoding="utf-8"))
            self.assertEqual(plan["code"]["commit"], fresh["baseline_commit"], name)
            self.assertFalse(plan["config"]["smoke_compaction"])
            self.assertEqual(plan["config"]["recorded_image"]["id"], recorded["id"])
            self.assertIs(plan["config"]["recorded_image"]["matches_pin"], False)
        self.assertEqual(row["selection_code_commit"], fresh["baseline_commit"])
        self.assertEqual(row["confirmation_code_commit"], fresh["baseline_commit"])
        self.assertEqual(row["confirmation_baseline_code_commit"], fresh["baseline_commit"])
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


class Commits(unittest.TestCase):
    """``evaluate`` refuses an arm whose code_commit differs from the fresh baseline."""

    def setUp(self):
        self.inner = EndToEnd()
        self.inner.setUp()
        self.addCleanup(self.inner.doCleanups)

    def test_mismatched_code_commit_on_any_arm_is_refused(self):
        proposal = self.inner.proposal()
        commit = rn.code_commit()["commit"]
        self.inner._set_baseline(proposal, baseline_commit=commit, code_commit="other-commit",
                                 passes=0, completed=2, set_aside=0)
        fresh = self.inner.arms(select=1, confirm=1, confirm_baseline=0)
        with self.assertRaisesRegex(ValueError, "fresh baseline code_commit"):
            idn.evaluate(self.inner.run, proposal, fresh, n_trials=2)
        self.assertEqual(fresh.calls, [])
        self.inner._set_baseline(proposal, baseline_commit=commit, code_commit=commit)

        other = "0" * 40

        def fake_at(bad_at):
            state = {"n": 0}

            def fake(root=None):
                state["n"] += 1
                return {"commit": other if state["n"] == bad_at else commit, "branch": "main", "dirty": False}
            return fake

        for bad_at, arm, calls in ((1, "selection", 2), (2, "confirmation", 4), (3, "confirmation-baseline", 6)):
            alt = dict(proposal, proposal_id=proposal["proposal_id"] + f"-{arm}")
            executor = self.inner.arms(select=1, confirm=1, confirm_baseline=0)
            results = self.inner.run / "ideation_results.jsonl"
            before = results.read_text(encoding="utf-8") if results.exists() else ""
            with mock_patch("obench.reflection.runner.code_commit", fake_at(bad_at)):
                with self.assertRaisesRegex(ValueError, f"{arm} code_commit"):
                    idn.evaluate(self.inner.run, alt, executor, n_trials=2)
            self.assertEqual(len(executor.calls), calls, arm)
            after = results.read_text(encoding="utf-8") if results.exists() else ""
            self.assertEqual(after, before, arm)

        matched = self.inner.arms(select=1, confirm=1, confirm_baseline=0)
        citations = [{"method": "A", "evidence": "A:failing_step", "pointer": "credit_a.jsonl#t#step=1"}]
        cited = dict(proposal, proposal_id=proposal["proposal_id"] + "-match", citations=citations, uncited=False)
        row = idn.evaluate(self.inner.run, cited, matched, n_trials=2)
        self.assertEqual(row["citations"], citations)
        self.assertFalse(row["uncited"])
        self.assertEqual((row["code_commit"], row["selection_code_commit"], row["confirmation_code_commit"],
                          row["confirmation_baseline_code_commit"]), (commit, commit, commit, commit))
        for label, rel in (("selection", row["selection_run_dir"]),
                           ("confirmation", row["confirmation_run_dirs"][0]),
                           ("confirmation-baseline", row["confirmation_run_dirs"][1])):
            summary = rn.read_rows(self.inner.run / rel / "summary.jsonl")[0]
            self.assertEqual(summary["code_commit"], commit, label)


def _evidence_ids(prompt: str) -> list[str]:
    payload = json.loads(prompt[prompt.index("{\n"):])
    return [item["id"] for item in payload["credit"]["evidence"]]


def _cited(i, *ids, method=None):
    alt = good(i)
    if method == "both":
        alt["citations"] = [{"method": "both", "evidence": list(ids)}]
    else:
        alt["citations"] = [{"method": item.split(":", 1)[0], "evidence": item} for item in ids]
    return alt


class CombinedIdeation(unittest.TestCase):
    """One ideator call per drawn failure, with A and B evidence in that one input."""

    def setUp(self):
        from obench.reflection import credit_a, credit_b
        from obench.tests.test_reflection_credit_a import call, step
        from obench.tests.test_reflection_credit_b import FakeJudge

        self.run = Path(tempfile.mkdtemp())
        short = [step(1, call("bash", "ok")), step(2, call("bash", "ok")), step(3, call("bash", "error: boom"))]
        early = [step(1, call("bash", "file: command not found"))]
        late = [step(n, call("bash", "ok")) for n in range(1, 6)] + [step(6, call("bash", "error: late"))]
        trials = []
        for i, trace in enumerate((short, early, late)):
            rel = f"trials/m/extract-elf/{i}/trace.jsonl"
            path = self.run / rel
            path.parent.mkdir(parents=True)
            path.write_text("".join(json.dumps(s) + "\n" for s in trace), encoding="utf-8")
            trials.append({"run_id": "r", "trial_id": f"t{i}", "task": "extract-elf", "model": OPUS,
                           "patch_id": None, "trial_index": i, "status": "completed", "passed": False, "trace": rel})
        (self.run / "trials.jsonl").write_text("".join(json.dumps(t) + "\n" for t in trials), encoding="utf-8")
        self.cell = f"{OPUS}/extract-elf"
        (self.run / "credit_draw.json").write_text(json.dumps({
            self.cell: {"status": "IN", "picks": [
                {"draw_order": 1, "slot": 0, "trial_id": "t0"},
                {"draw_order": 2, "slot": 1, "trial_id": "t1"},
            ]},
            f"{OPUS}/not-in-the-run": {"status": "NO_ROWS", "reason": "no rows in trials.jsonl", "picks": []},
        }), encoding="utf-8")
        credit_a.run_method_a(self.run)
        self.judge = FakeJudge({1: "near_error"})
        credit_b.run_method_b(self.run, self.judge)

    def test_one_call_per_failure_and_step_one_sends_only_method_a(self):
        from obench.reflection import credit_agreement as agr

        both = _cited(0, "A:failing_step", "B:step:2", method="both")
        rest = [_cited(i, "A:failing_step", "B:window") for i in range(1, 5)]
        only_a = [_cited(i, "A:failing_step") for i in range(5)]
        ideator = FakeIdeator([both, *rest], only_a)
        rows = idn.propose_drawn(self.run, ideator)
        self.assertEqual(len(ideator.prompts), 2)  # one per drawn failure, not one per method, not the undrawn t2

        short_ids = _evidence_ids(ideator.prompts[0])
        self.assertIn("A:failing_step", short_ids)
        self.assertIn("B:window", short_ids)
        self.assertEqual([item for item in short_ids if item.startswith("B:step:")], ["B:step:1", "B:step:2"])
        early_ids = _evidence_ids(ideator.prompts[1])
        self.assertEqual(early_ids, ["A:failing_step"])
        self.assertNotIn("B:window", ideator.prompts[1])
        self.assertNotIn("B:step:", ideator.prompts[1])

        by_parent = {}
        for row in rows:
            by_parent.setdefault(row["parent_trial_id"], []).append(row)
        self.assertEqual(set(by_parent), {"t0", "t1"})
        self.assertTrue(all(row["status"] == "accepted" and row["uncited"] is False for row in rows))
        self.assertEqual(by_parent["t0"][0]["ideator_evidence"], ["A", "B"])
        self.assertEqual(by_parent["t0"][0]["method_b_status"], "ok")
        self.assertEqual(by_parent["t0"][0]["method_b_window_length"], 2)
        self.assertEqual(by_parent["t0"][0]["credit_method"], "A+B")
        both_row = by_parent["t0"][0]
        self.assertEqual(both_row["citations"][0]["method"], "both")
        self.assertEqual(both_row["citations"][0]["evidence"], ["A:failing_step", "B:step:2"])
        self.assertEqual(len(both_row["citations"][0]["pointer"]), 2)
        self.assertTrue(any("credit_b.jsonl#t0#step=2" in pointer for pointer in both_row["citations"][0]["pointer"]))
        self.assertEqual(by_parent["t1"][0]["ideator_evidence"], ["A"])
        self.assertEqual(by_parent["t1"][0]["method_b_status"], "empty_window")
        self.assertEqual(by_parent["t1"][0]["method_b_window_length"], 0)
        self.assertEqual(set(by_parent["t1"][0]["credit_rows"]), {"A", "B"})
        self.assertIn("step=1", by_parent["t1"][0]["citations"][0]["pointer"])

        b_rows = {row["trial_id"]: row for row in rn.read_rows(self.run / "credit_b.jsonl")}
        self.assertEqual((b_rows["t0"]["status"], b_rows["t0"]["window_length"], b_rows["t0"]["window"]), ("ok", 2, [1, 2]))
        self.assertLess(b_rows["t0"]["window_length"], b_rows["t0"]["k"])
        self.assertEqual((b_rows["t1"]["status"], b_rows["t1"]["window"], b_rows["t1"]["window_length"]),
                         ("empty_window", [], 0))
        self.assertEqual(len(self.judge.prompts), 1)  # t1 is empty_window; undrawn t2 is not judged
        self.assertNotIn("t2", b_rows)
        flags = {row["trial_id"]: row for row in agr.run_agreement(self.run)}
        self.assertEqual(set(flags), {"t0", "t1"})
        self.assertTrue(flags["t0"]["probe_error"] and flags["t0"]["probe_error_step"] == 3)
        self.assertTrue(flags["t1"]["probe_error"] and flags["t1"]["probe_error_step"] == 1)
        self.assertEqual(flags["t0"]["earliest_near_error_step"], 1)
        self.assertEqual(flags["t0"]["steps_before_a"], 2)  # A's step 3 minus the near-error at step 1
        self.assertTrue(flags["t0"]["same_step"])
        self.assertIsNone(flags["t1"]["earliest_near_error_step"])
        self.assertIsNone(flags["t1"]["steps_before_a"])

    def test_an_alternative_without_a_citation_is_rejected(self):
        cited = [_cited(i, "A:failing_step", "B:step:1") for i in range(4)]
        bad = cited + [good(4)]
        only_a = [_cited(i, "A:failing_step") for i in range(5)]
        ideator = FakeIdeator(bad, bad, only_a)
        rows = idn.propose_drawn(self.run, ideator)
        self.assertEqual(len(ideator.prompts), 3)  # the uncited set is re-asked once, then the step-1 failure
        self.assertIn("no citation", ideator.prompts[1])
        first = [row for row in rows if row["parent_trial_id"] == "t0"]
        self.assertEqual([row["status"] for row in first], ["accepted"] * 4 + ["rejected"])
        self.assertTrue(first[4]["uncited"])
        self.assertIn("no citation", first[4]["rejection_reasons"])
        self.assertIsNone(first[4]["proposal_id"])
        self.assertEqual(first[4]["citations"], [])
        self.assertTrue(all(row["uncited"] is False and row["citations"] for row in first[:4]))


class ConfirmMode(unittest.TestCase):
    """``confirm=all`` confirms every candidate. ``confirm=top`` confirms one per cell."""

    def setUp(self):
        p = mock_patch.dict(os.environ, {hs_config.CUTOFF_ENV: ""})
        p.start()
        self.addCleanup(p.stop)

    def _run(self, n=2):
        run = Path(tempfile.mkdtemp())
        cfg = rn.RunConfig.from_dict({"run_id": "base", "suite": "pilot", "models": [OPUS], "n_trials": n,
                                      "tasks": ["extract-elf"], "max_rounds": 1})
        rn.Runner(cfg, run, rn.FixtureExecutor({})).run()
        from obench.reflection import credit_a
        credit_a.run_method_a(run)
        host = EndToEnd()
        host.run = run
        host._install_fresh_baseline()
        return run, [row for row in rn.read_rows(run / "trials.jsonl") if row["passed"] is False]

    def _proposal(self, trial, index, text):
        patch = {"schema": pt.PATCH_SCHEMA, "ops": [{"op": "system_append", "text": text}]}
        return {"schema": idn.PROPOSAL_SCHEMA, "status": "accepted", "uncited": False, "index": index,
                "proposal_id": pt.patch_id(patch), "patch": patch, "parent_trial_id": trial["trial_id"],
                "task": trial["task"], "model": trial["model"], "credit_method": "A", "citations": []}

    def _write(self, run, proposals):
        (run / "ideation.jsonl").write_text("".join(json.dumps(row) + "\n" for row in proposals), encoding="utf-8")

    def _draw(self, run, trials, cell=None):
        cell = cell or f"{trials[0]['model']}/{trials[0]['task']}"
        (run / "credit_draw.json").write_text(json.dumps({
            cell: {"status": "IN", "picks": [
                {"draw_order": i + 1, "slot": trial.get("trial_index", i), "trial_id": trial["trial_id"]}
                for i, trial in enumerate(trials)]},
        }), encoding="utf-8")

    def _executor(self, by_id, confirm_passes=2, baseline_passes=0):
        class SelectPasses(rn.FixtureExecutor):
            def run_trial(self, spec, run_dir):
                if "--confirm-baseline--" in spec.run_id:
                    passes = baseline_passes
                elif "--confirm--" in spec.run_id:
                    passes = confirm_passes
                else:
                    passes = by_id[spec.patch_id]
                self.passes = {(spec.task, spec.model): passes}
                return super().run_trial(spec, run_dir)
        return SelectPasses({})

    def _results(self, run):
        return rn.read_rows(run / "ideation_results.jsonl")

    def test_confirm_all_confirms_every_candidate_and_records_the_mode(self):
        run, trials = self._run()
        proposals = [self._proposal(trials[0], 0, "a"), self._proposal(trials[0], 1, "b"),
                     self._proposal(trials[0], 2, "c")]
        self._write(run, proposals)
        # Passes 1 and 2 beat a 0 baseline. Passes 0 does not. Both candidates are confirmed.
        executor = self._executor({proposals[0]["proposal_id"]: 1, proposals[1]["proposal_id"]: 0,
                                   proposals[2]["proposal_id"]: 2})
        for proposal in proposals:
            idn.evaluate(run, proposal, executor, n_trials=2)  # default confirm=all
        rows = {row["alternative_index"]: row for row in self._results(run)}
        self.assertEqual(set(rows), {0, 1, 2})
        self.assertTrue(all(row["confirm"] == "all" and row["confirm_k"] == 1 and row["confirm_skipped"] is None
                            for row in rows.values()))
        self.assertEqual(rows[1]["candidate"], False)
        self.assertIsNone(rows[1]["confirmation_alt_passes"])
        self.assertTrue(rows[0]["confirmed"] and rows[2]["confirmed"])
        self.assertEqual(len(executor.calls), 3 * 2 + 2 * 4)  # three selections, two confirmations
        with self.assertRaisesRegex(ValueError, "confirm"):
            idn.evaluate(run, proposals[0], executor, n_trials=2, confirm="maybe")

    def test_confirm_top_keeps_only_the_best_candidate_per_failure(self):
        run, trials = self._run()
        self._draw(run, [trials[0]])
        # index 0 passes 1; index 1 and 2 both pass 2. Same draw, so the lower index wins.
        low = self._proposal(trials[0], 0, "low")
        tied_high_index = self._proposal(trials[0], 2, "high-index")
        tied_low_index = self._proposal(trials[0], 1, "low-index")
        proposals = [low, tied_high_index, tied_low_index]
        self._write(run, proposals)
        executor = self._executor({low["proposal_id"]: 1, tied_high_index["proposal_id"]: 2,
                                   tied_low_index["proposal_id"]: 2})
        idn.evaluate(run, low, executor, n_trials=2, confirm="top")
        idn.evaluate(run, tied_high_index, executor, n_trials=2, confirm="top")
        mid = self._results(run)
        self.assertEqual(len(mid), 2)
        self.assertTrue(all(row["confirm"] == "top" and row["confirm_k"] == 1 and row["confirmation_run_dirs"] is None
                            for row in mid))
        self.assertTrue(all(row["confirm_skipped"] is None and row["confirmed"] is None for row in mid))
        winner = idn.evaluate(run, tied_low_index, executor, n_trials=2, confirm="top")
        rows = {row["alternative_index"]: row for row in self._results(run)}
        self.assertTrue(all(row["confirm"] == "top" and row["confirm_k"] == 1 for row in rows.values()))
        self.assertEqual(winner["alternative_index"], 1)
        self.assertTrue(rows[1]["confirmed"] and rows[1]["confirm_skipped"] is None)
        self.assertEqual(rows[1]["selection_alt_passes"], 2)
        for index in (0, 2):
            self.assertTrue(rows[index]["candidate"])
            self.assertEqual(rows[index]["confirm_skipped"], "not_top")
            self.assertIsNone(rows[index]["confirmed"])
            self.assertFalse(rows[index]["success"])
            for field in ("confirmation_baseline_passes", "confirmation_baseline_completed",
                          "confirmation_alt_passes", "confirmation_alt_completed",
                          "confirmation_beats_baseline", "confirmation_complete", "confirmation_fisher_p",
                          "confirmation_spend_usd", "confirmation_run_dirs", "confirmation_run_states",
                          "confirmation_code_commit", "confirmation_baseline_code_commit"):
                self.assertIsNone(rows[index][field], field)
        self.assertEqual(len(executor.calls), 3 * 2 + 4)  # selections for three, confirmation for one

    def test_top_candidate_ignores_fisher_and_prefers_earlier_draw(self):
        # More passes beat an earlier pick. A pass-count tie ignores Fisher p:
        # the earlier draw wins even with a worse p and a higher index.
        rows = [
            {"candidate": True, "selection_alt_passes": 2, "selection_fisher_p": 0.01,
             "draw_order": 1, "alternative_index": 0, "proposal_id": "early-fewer"},
            {"candidate": True, "selection_alt_passes": 4, "selection_fisher_p": 0.9,
             "draw_order": 2, "alternative_index": 5, "proposal_id": "late-more"},
        ]
        self.assertEqual(idn.top_candidate(rows)["proposal_id"], "late-more")
        tied = [
            {"candidate": True, "selection_alt_passes": 4, "selection_fisher_p": 0.01,
             "draw_order": 2, "alternative_index": 0, "proposal_id": "later-sharper"},
            {"candidate": True, "selection_alt_passes": 4, "selection_fisher_p": 0.9,
             "draw_order": 1, "alternative_index": 9, "proposal_id": "earlier"},
        ]
        self.assertEqual(idn.top_candidate(tied)["proposal_id"], "earlier")
        same_draw = [
            {"candidate": True, "selection_alt_passes": 4, "selection_fisher_p": 0.01,
             "draw_order": 1, "alternative_index": 3, "proposal_id": "b"},
            {"candidate": True, "selection_alt_passes": 4, "selection_fisher_p": 0.9,
             "draw_order": 1, "alternative_index": 1, "proposal_id": "a"},
        ]
        self.assertEqual(idn.top_candidate(same_draw)["proposal_id"], "a")
        self.assertIsNone(idn.top_candidate([{"candidate": False, "selection_alt_passes": 9,
                                              "draw_order": 1, "alternative_index": 0}]))

    def test_same_patch_on_two_failures_keeps_both_results(self):
        run, trials = self._run()
        self._draw(run, trials)
        first = self._proposal(trials[0], 0, "same-patch")
        second = dict(first, parent_trial_id=trials[1]["trial_id"])
        self.assertEqual(first["proposal_id"], second["proposal_id"])
        self._write(run, [first, second])
        executor = self._executor({first["proposal_id"]: 0})
        idn.evaluate(run, first, executor, n_trials=2, confirm="top")
        idn.evaluate(run, second, executor, n_trials=2, confirm="top")
        rows = self._results(run)
        self.assertEqual(sorted(row["parent_trial_id"] for row in rows),
                         sorted(trial["trial_id"] for trial in trials))
        self.assertTrue(all(row["proposal_id"] == first["proposal_id"] for row in rows))
        self.assertTrue(all(row["candidate"] is False and row["confirm_skipped"] is None for row in rows))
        self.assertTrue(all(row["confirmation_alt_passes"] is None for row in rows))

    def test_one_cell_confirms_one_candidate_across_two_failures(self):
        run, trials = self._run()
        self._draw(run, trials)  # trials[0] is the earlier pick
        early = self._proposal(trials[0], 0, "early")
        late = self._proposal(trials[1], 0, "late")
        self._write(run, [early, late])
        executor = self._executor({early["proposal_id"]: 1, late["proposal_id"]: 2})
        idn.evaluate(run, early, executor, n_trials=2, confirm="top")
        self.assertTrue(all(row["confirmation_run_dirs"] is None for row in self._results(run)))
        idn.evaluate(run, late, executor, n_trials=2, confirm="top")
        by_parent = {row["parent_trial_id"]: row for row in self._results(run)}
        self.assertEqual(sum(1 for row in by_parent.values() if row["confirmed"]), 1)
        self.assertTrue(by_parent[trials[1]["trial_id"]]["confirmed"])
        self.assertEqual(by_parent[trials[1]["trial_id"]]["selection_alt_passes"], 2)
        skipped = by_parent[trials[0]["trial_id"]]
        self.assertTrue(skipped["candidate"])
        self.assertEqual(skipped["confirm_skipped"], "not_top")
        self.assertIsNone(skipped["confirmed"])
        self.assertIsNone(skipped["confirmation_alt_passes"])
        self.assertEqual(len(executor.calls), 2 * 2 + 4)

    def test_pass_tie_across_failures_goes_to_the_earlier_draw(self):
        run, trials = self._run()
        self._draw(run, trials)
        # Same passes, so the same Fisher p. The later pick has the lower index and still loses.
        early = self._proposal(trials[0], 4, "early-high-index")
        late = self._proposal(trials[1], 0, "late-low-index")
        self._write(run, [early, late])
        executor = self._executor({early["proposal_id"]: 1, late["proposal_id"]: 1})
        idn.evaluate(run, late, executor, n_trials=2, confirm="top")
        idn.evaluate(run, early, executor, n_trials=2, confirm="top")
        by_parent = {row["parent_trial_id"]: row for row in self._results(run)}
        winner = by_parent[trials[0]["trial_id"]]
        loser = by_parent[trials[1]["trial_id"]]
        self.assertTrue(winner["confirmed"])
        self.assertEqual(winner["draw_order"], 1)
        self.assertEqual(winner["selection_alt_passes"], loser["selection_alt_passes"])
        self.assertEqual(winner["selection_fisher_p"], loser["selection_fisher_p"])
        self.assertGreater(winner["alternative_index"], loser["alternative_index"])
        self.assertTrue(loser["candidate"])
        self.assertEqual(loser["confirm_skipped"], "not_top")
        self.assertIsNone(loser["confirmation_alt_passes"])
        self.assertIsNone(loser["confirmation_fisher_p"])

    def test_cli_flag_overrides_config(self):
        run, trials = self._run()
        ideator = FakeIdeator([good(i) for i in range(5)])
        idn.propose(run, trials[0], "A", ideator)
        self._draw(run, [trials[0]])
        fixture = run / "passes.json"
        fixture.write_text(json.dumps({f"extract-elf|{OPUS}": 1}), encoding="utf-8")
        config = run / "ideation-config.json"
        config.write_text(json.dumps({"confirm": "top"}), encoding="utf-8")
        self.assertEqual(idn.resolve_config(config, None).confirm, "top")
        self.assertEqual(idn.resolve_config(config, "all").confirm, "all")
        self.assertEqual(idn.resolve_config(None, None).confirm, "all")
        # Config key alone: no --confirm flag.
        self.assertEqual(idn.main(["--run", str(run), "--fixture", str(fixture), "--config", str(config),
                                   "--n-trials", "2"]), 0)
        rows = self._results(run)
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(row["confirm"] == "top" and row["candidate"] for row in rows))
        confirmed = [row for row in rows if row["confirmation_alt_passes"] is not None]
        skipped = [row for row in rows if row["confirm_skipped"] == "not_top"]
        self.assertEqual(len(confirmed), 1)
        self.assertEqual(confirmed[0]["alternative_index"], 0)
        self.assertEqual(len(skipped), 4)
        self.assertTrue(all(row["confirmation_alt_passes"] is None for row in skipped))

        other, other_trials = self._run()
        idn.propose(other, other_trials[0], "A", FakeIdeator([good(i) for i in range(5)]))
        self._draw(other, [other_trials[0]])
        other_fixture = other / "passes.json"
        other_fixture.write_text(fixture.read_text(), encoding="utf-8")
        other_config = other / "ideation-config.json"
        other_config.write_text(json.dumps({"confirm": "top"}), encoding="utf-8")
        # The flag overrides the config file.
        self.assertEqual(idn.main(["--run", str(other), "--fixture", str(other_fixture), "--config", str(other_config),
                                   "--confirm", "all", "--n-trials", "2"]), 0)
        all_rows = self._results(other)
        self.assertEqual(len(all_rows), 5)
        self.assertTrue(all(row["confirm"] == "all" and row["confirm_k"] == 1 and row["confirm_skipped"] is None
                            for row in all_rows))
        self.assertTrue(all(row["confirmation_alt_passes"] == 1 for row in all_rows))

    def _canon_rows(self, rows):
        """Serialized result rows with ``confirm_k`` removed."""
        return "".join(
            json.dumps({key: value for key, value in row.items() if key != "confirm_k"}, sort_keys=True) + "\n"
            for row in rows)

    def _ideation_at_0ea7671c(self):
        cached = getattr(ConfirmMode, "_baseline_ideation", None)
        if cached is not None:
            return cached
        rev = "0ea7671c0acc17da23ab92852cc9af17ae8db863"
        source = subprocess.check_output(
            ["git", "show", f"{rev}:obench/reflection/ideation.py"],
            cwd=Path(__file__).resolve().parents[2])
        path = Path(tempfile.mkdtemp()) / "ideation_0ea7671c.py"
        path.write_bytes(source)
        name = "ideation_baseline_0ea7671c"
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        ConfirmMode._baseline_ideation = module
        return module

    def _assert_k1_matches_baseline(self, drive, name):
        """``confirm_k`` 1 matches ``confirm=top`` rows from main 0ea7671c, aside from the new field."""
        old_rows = drive(self._ideation_at_0ea7671c().evaluate)
        default_rows = drive(idn.evaluate)

        def explicit(*args, **kwargs):
            kwargs["confirm_k"] = 1
            return idn.evaluate(*args, **kwargs)

        explicit_rows = drive(explicit)
        self.assertEqual(self._canon_rows(default_rows), self._canon_rows(old_rows), name)
        self.assertEqual(self._canon_rows(explicit_rows), self._canon_rows(old_rows), name)
        self.assertTrue(old_rows, name)
        self.assertTrue(all("confirm_k" not in row for row in old_rows), name)
        self.assertTrue(all(row["confirm_k"] == 1 for row in default_rows), name)
        self.assertTrue(all(row["confirm_k"] == 1 for row in explicit_rows), name)

    def test_confirm_k_one_matches_top_rows_on_0ea7671c(self):
        def best_of_three(evaluate):
            run, trials = self._run()
            self._draw(run, [trials[0]])
            low = self._proposal(trials[0], 0, "low")
            tied_high_index = self._proposal(trials[0], 2, "high-index")
            tied_low_index = self._proposal(trials[0], 1, "low-index")
            self._write(run, [low, tied_high_index, tied_low_index])
            executor = self._executor({low["proposal_id"]: 1, tied_high_index["proposal_id"]: 2,
                                       tied_low_index["proposal_id"]: 2})
            for proposal in (low, tied_high_index, tied_low_index):
                evaluate(run, proposal, executor, n_trials=2, confirm="top")
            return self._results(run)

        def across_failures(evaluate):
            run, trials = self._run()
            self._draw(run, trials)
            early = self._proposal(trials[0], 0, "early")
            late = self._proposal(trials[1], 0, "late")
            self._write(run, [early, late])
            executor = self._executor({early["proposal_id"]: 1, late["proposal_id"]: 2})
            evaluate(run, early, executor, n_trials=2, confirm="top")
            evaluate(run, late, executor, n_trials=2, confirm="top")
            return self._results(run)

        def earlier_draw(evaluate):
            run, trials = self._run()
            self._draw(run, trials)
            early = self._proposal(trials[0], 4, "early-high-index")
            late = self._proposal(trials[1], 0, "late-low-index")
            self._write(run, [early, late])
            executor = self._executor({early["proposal_id"]: 1, late["proposal_id"]: 1})
            evaluate(run, late, executor, n_trials=2, confirm="top")
            evaluate(run, early, executor, n_trials=2, confirm="top")
            return self._results(run)

        def same_patch(evaluate):
            run, trials = self._run()
            self._draw(run, trials)
            first = self._proposal(trials[0], 0, "same-patch")
            second = dict(first, parent_trial_id=trials[1]["trial_id"])
            self._write(run, [first, second])
            executor = self._executor({first["proposal_id"]: 0})
            evaluate(run, first, executor, n_trials=2, confirm="top")
            evaluate(run, second, executor, n_trials=2, confirm="top")
            return self._results(run)

        def still_pending(evaluate):
            run, trials = self._run()
            self._draw(run, trials)
            early = self._proposal(trials[0], 0, "early")
            late = self._proposal(trials[1], 0, "late")
            self._write(run, [early, late])
            executor = self._executor({early["proposal_id"]: 1, late["proposal_id"]: 2})
            evaluate(run, early, executor, n_trials=2, confirm="top")
            return self._results(run)

        def confirm_all(evaluate):
            run, trials = self._run()
            proposals = [self._proposal(trials[0], 0, "a"), self._proposal(trials[0], 1, "b"),
                         self._proposal(trials[0], 2, "c")]
            self._write(run, proposals)
            executor = self._executor({proposals[0]["proposal_id"]: 1, proposals[1]["proposal_id"]: 0,
                                       proposals[2]["proposal_id"]: 2})
            for proposal in proposals:
                evaluate(run, proposal, executor, n_trials=2)
            return self._results(run)

        self._assert_k1_matches_baseline(best_of_three, "best of three")
        self._assert_k1_matches_baseline(across_failures, "across failures")
        self._assert_k1_matches_baseline(earlier_draw, "earlier draw")
        self._assert_k1_matches_baseline(same_patch, "same patch")
        self._assert_k1_matches_baseline(still_pending, "still pending")
        self._assert_k1_matches_baseline(confirm_all, "confirm all")

    def test_confirm_k_keeps_the_top_three_of_five_across_two_failures(self):
        run, trials = self._run(4)
        early_trial, late_trial = trials[0], trials[1]
        self._draw(run, [early_trial, late_trial])
        ranked_text = []
        i = 0
        while len(ranked_text) < 3:
            text = f"rank-{i}"
            ranked_text.append((self._proposal(late_trial, 0, text)["proposal_id"], text))
            i += 1
        ranked_text.sort()
        high_index_text, low_id_text, high_id_text = (text for _, text in ranked_text)
        self.assertLess(self._proposal(late_trial, 0, high_index_text)["proposal_id"],
                        self._proposal(late_trial, 0, low_id_text)["proposal_id"])
        self.assertLess(self._proposal(late_trial, 0, low_id_text)["proposal_id"],
                        self._proposal(late_trial, 0, high_id_text)["proposal_id"])
        high_id = self._proposal(late_trial, 1, high_id_text)
        high_index = self._proposal(late_trial, 2, high_index_text)
        most = self._proposal(late_trial, 9, "most-passes")
        low_id = self._proposal(late_trial, 1, low_id_text)
        early = self._proposal(early_trial, 5, "early-draw")
        proposals = [high_id, high_index, most, low_id, early]
        labels = {row["proposal_id"]: name for row, name in (
            (high_id, "high-id"), (high_index, "high-index"), (most, "most"),
            (low_id, "low-id"), (early, "early"))}
        self._write(run, proposals)
        executor = self._executor({most["proposal_id"]: 4, early["proposal_id"]: 3, low_id["proposal_id"]: 3,
                                   high_id["proposal_id"]: 3, high_index["proposal_id"]: 3})
        for proposal in (high_id, high_index, most, low_id):
            idn.evaluate(run, proposal, executor, n_trials=4, confirm="top", confirm_k=3)
        pending = self._results(run)
        self.assertEqual(len(pending), 4)
        self.assertTrue(all(row["confirm_k"] == 3 and row["confirm_skipped"] is None and row["confirmed"] is None
                            and row["confirmation_run_dirs"] is None for row in pending))
        idn.evaluate(run, early, executor, n_trials=4, confirm="top", confirm_k=3)
        rows = self._results(run)
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(row["confirm"] == "top" and row["confirm_k"] == 3 for row in rows))
        confirmed = {labels[row["proposal_id"]] for row in rows if row["confirmation_alt_passes"] is not None}
        skipped = {labels[row["proposal_id"]] for row in rows if row["confirm_skipped"] == "not_top"}
        self.assertEqual(confirmed, {"most", "early", "low-id"})
        self.assertEqual(skipped, {"high-id", "high-index"})
        by_label = {labels[row["proposal_id"]]: row for row in rows}
        self.assertGreater(by_label["most"]["selection_alt_passes"], by_label["early"]["selection_alt_passes"])
        self.assertLess(by_label["early"]["draw_order"], by_label["low-id"]["draw_order"])
        self.assertEqual(by_label["early"]["selection_alt_passes"], by_label["low-id"]["selection_alt_passes"])
        self.assertGreater(by_label["early"]["alternative_index"], by_label["low-id"]["alternative_index"])
        self.assertEqual(by_label["low-id"]["alternative_index"], by_label["high-id"]["alternative_index"])
        self.assertEqual(by_label["low-id"]["draw_order"], by_label["high-id"]["draw_order"])
        self.assertLess(by_label["low-id"]["proposal_id"], by_label["high-id"]["proposal_id"])
        self.assertLess(by_label["high-index"]["proposal_id"], by_label["low-id"]["proposal_id"])
        self.assertGreater(by_label["high-index"]["alternative_index"], by_label["low-id"]["alternative_index"])
        order = [labels[row["proposal_id"]] for row in idn.top_candidates(rows, 5)]
        self.assertEqual(order, ["most", "early", "low-id", "high-id", "high-index"])
        for name in ("high-id", "high-index"):
            self.assertTrue(by_label[name]["candidate"])
            self.assertIsNone(by_label[name]["confirmed"])
            self.assertIsNone(by_label[name]["confirmation_baseline_passes"])
        baselines = []
        for name in ("most", "early", "low-id"):
            row = by_label[name]
            self.assertTrue(row["confirmed"])
            self.assertIsNone(row["confirm_skipped"])
            trial_rows = rn.read_rows(run / row["confirmation_run_dirs"][1] / "trials.jsonl")
            self.assertEqual(len(trial_rows), 4)
            baselines.append({item["trial_id"] for item in trial_rows})
        self.assertEqual(len(set().union(*baselines)), 12)

    def test_confirm_k_confirms_every_candidate_when_the_cell_has_fewer(self):
        run, trials = self._run()
        self._draw(run, [trials[0]])
        first = self._proposal(trials[0], 0, "first")
        second = self._proposal(trials[0], 1, "second")
        miss = self._proposal(trials[0], 2, "miss")
        self._write(run, [first, second, miss])
        executor = self._executor({first["proposal_id"]: 1, second["proposal_id"]: 2, miss["proposal_id"]: 0})
        for proposal in (first, second, miss):
            idn.evaluate(run, proposal, executor, n_trials=2, confirm="top", confirm_k=3)
        rows = {row["alternative_index"]: row for row in self._results(run)}
        self.assertTrue(all(row["confirm_k"] == 3 and row["confirm"] == "top" for row in rows.values()))
        self.assertTrue(rows[0]["confirmed"] and rows[1]["confirmed"])
        self.assertFalse(rows[2]["candidate"])
        self.assertIsNone(rows[2]["confirm_skipped"])
        self.assertIsNone(rows[2]["confirmed"])
        self.assertFalse(any(row["confirm_skipped"] == "not_top" for row in rows.values()))
        bases = {tuple(row["confirmation_run_dirs"]) for row in rows.values() if row["confirmed"]}
        self.assertEqual(len(bases), 2)

    def test_same_patch_confirm_k_keeps_a_fresh_baseline_per_failure(self):
        n = rn.N_TRIALS
        run, trials = self._run(n)
        pair = trials[:2]
        self._draw(run, pair)
        first = self._proposal(pair[0], 0, "same-patch")
        second = dict(first, parent_trial_id=pair[1]["trial_id"])
        self.assertEqual(first["proposal_id"], second["proposal_id"])
        self._write(run, [first, second])
        executor = self._executor({first["proposal_id"]: 1})
        idn.evaluate(run, first, executor, n_trials=n, confirm="top", confirm_k=2)
        idn.evaluate(run, second, executor, n_trials=n, confirm="top", confirm_k=2)
        rows = self._results(run)
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            sorted((row["parent_trial_id"], row["proposal_id"]) for row in rows),
            sorted((trial["trial_id"], first["proposal_id"]) for trial in pair))
        self.assertTrue(all(row["confirmed"] and row["confirm_k"] == 2 and row["confirm_skipped"] is None
                            for row in rows))
        self.assertEqual(len({tuple(row["confirmation_run_dirs"]) for row in rows}), 2)
        baseline_ids = []
        for row in rows:
            self.assertEqual(row["confirmation_baseline_completed"], n)
            self.assertEqual(row["confirmation_alt_completed"], n)
            trial_rows = rn.read_rows(run / row["confirmation_run_dirs"][1] / "trials.jsonl")
            self.assertEqual(len(trial_rows), n)
            baseline_ids.append({item["trial_id"] for item in trial_rows})
        self.assertFalse(baseline_ids[0] & baseline_ids[1])
        baseline_calls = [call for call in executor.calls if "--confirm-baseline--" in call.run_id]
        alt_calls = [call for call in executor.calls if "--confirm--" in call.run_id]
        self.assertEqual(len({call.run_id for call in baseline_calls}), 2)
        self.assertEqual(len(baseline_calls), 2 * n)
        self.assertEqual(len({call.run_id for call in alt_calls}), 2)
        self.assertEqual(len(alt_calls), 2 * n)

    def test_confirm_k_below_one_and_with_confirm_all_is_rejected(self):
        run, trials = self._run()
        proposal = self._proposal(trials[0], 0, "a")
        executor = self._executor({proposal["proposal_id"]: 1})
        for bad in (0, -1, True, 1.5, "2"):
            with self.assertRaisesRegex(ValueError, "confirm_k"):
                idn.evaluate(run, proposal, executor, n_trials=2, confirm="top", confirm_k=bad)
        with self.assertRaisesRegex(ValueError, "confirm_k"):
            idn.evaluate(run, proposal, executor, n_trials=2, confirm="all", confirm_k=2)
        self.assertFalse((run / "ideation_results.jsonl").exists())
        with self.assertRaisesRegex(ValueError, "confirm_k"):
            idn.IdeationConfig.from_dict({"confirm": "top", "confirm_k": 0})
        with self.assertRaisesRegex(ValueError, "confirm_k"):
            idn.IdeationConfig.from_dict({"confirm": "all", "confirm_k": 3})
        with self.assertRaisesRegex(ValueError, "confirm_k"):
            idn.IdeationConfig.from_dict({"confirm": "top", "confirm_k": True})
        self.assertEqual(idn.IdeationConfig.from_dict({"confirm": "all"}).confirm_k, 1)
        self.assertEqual(idn.IdeationConfig.from_dict({"confirm": "top", "confirm_k": 3}).confirm_k, 3)
        self.assertEqual(idn.resolve_config(None, None, None).confirm_k, 1)
        self.assertEqual(idn.resolve_config(None, "top", 3).confirm, "top")
        self.assertEqual(idn.resolve_config(None, "top", 3).confirm_k, 3)
        config = run / "ideation-config.json"
        config.write_text(json.dumps({"confirm": "top", "confirm_k": 3}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "confirm_k"):
            idn.resolve_config(config, "all", None)
        self.assertEqual(idn.resolve_config(config, "all", 1).confirm_k, 1)
        for bad in (0, -3):
            with self.assertRaisesRegex(ValueError, "confirm_k"):
                rn.ideation_estimate(rn.FixtureExecutor({}), {OPUS: 1}, confirm="top", cells={OPUS: 1}, confirm_k=bad)
        with self.assertRaisesRegex(ValueError, "confirm_k"):
            rn.ideation_estimate(rn.FixtureExecutor({}), {OPUS: 1}, confirm="all", confirm_k=4)
        with self.assertRaisesRegex(ValueError, "cell"):
            rn.ideation_estimate(rn.FixtureExecutor({}), {OPUS: 1}, confirm="top", confirm_k=3)
        with self.assertRaisesRegex(SystemExit, "confirm_k"):
            idn.main(["--run", "unused", "--fixture", "unused", "--confirm", "top", "--confirm-k", "0"])
        with self.assertRaisesRegex(SystemExit, "confirm_k"):
            idn.main(["--run", "unused", "--fixture", "unused", "--confirm", "all", "--confirm-k", "2"])

    def test_confirm_k_cli_confirms_that_many_and_records_it(self):
        run, trials = self._run()
        idn.propose(run, trials[0], "A", FakeIdeator([good(i) for i in range(5)]))
        self._draw(run, [trials[0]])
        fixture = run / "passes.json"
        fixture.write_text(json.dumps({f"extract-elf|{OPUS}": 1}), encoding="utf-8")
        config = run / "ideation-config.json"
        config.write_text(json.dumps({"confirm": "top", "confirm_k": 1}), encoding="utf-8")
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(idn.main(["--run", str(run), "--fixture", str(fixture), "--config", str(config),
                                       "--confirm-k", "3", "--n-trials", "2"]), 0)
        summary = json.loads(buf.getvalue())
        self.assertEqual((summary["confirm"], summary["confirm_k"]), ("top", 3))
        rows = self._results(run)
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(row["confirm"] == "top" and row["confirm_k"] == 3 for row in rows))
        confirmed = sorted(row["alternative_index"] for row in rows if row["confirmation_alt_passes"] is not None)
        skipped = sorted(row["alternative_index"] for row in rows if row["confirm_skipped"] == "not_top")
        self.assertEqual(confirmed, [0, 1, 2])
        self.assertEqual(skipped, [3, 4])

    def _arm_inputs(self, run, proposal):
        base_cfg = json.loads((run / "plan.json").read_text(encoding="utf-8"))["config"]
        fresh = json.loads((run / "credit_baseline.json").read_text(encoding="utf-8"))
        cell = fresh[f"{proposal['model']}/{proposal['task']}"]
        recorded = {"ref": cell["image"]["ref"], "id": cell["image"]["id"],
                    "matches_pin": cell["image_matches_pin"]}
        return base_cfg, recorded

    def test_confirm_k_persists_each_winner_before_the_next(self):
        run, trials = self._run()
        self._draw(run, [trials[0]])
        proposals = [self._proposal(trials[0], index, f"rank-{index}") for index in range(3)]
        self._write(run, proposals)
        # n=2. Passes 2, then 1, then 1: rank is index 0, 1, 2. All three are candidates.
        executor = self._executor({proposals[0]["proposal_id"]: 2, proposals[1]["proposal_id"]: 1,
                                   proposals[2]["proposal_id"]: 1})
        for proposal in proposals[:2]:
            idn.evaluate(run, proposal, executor, n_trials=2, confirm="top", confirm_k=3)
        seen = []
        real = idn._run_confirmation

        def wrapped(*args, **kwargs):
            seen.append(args[2]["proposal_id"])
            if len(seen) == 2:
                raise RuntimeError("confirmation failed")
            return real(*args, **kwargs)

        with mock_patch.object(idn, "_run_confirmation", side_effect=wrapped):
            with self.assertRaisesRegex(RuntimeError, "confirmation failed"):
                idn.evaluate(run, proposals[2], executor, n_trials=2, confirm="top", confirm_k=3)
        self.assertEqual(seen, [proposals[0]["proposal_id"], proposals[1]["proposal_id"]])
        rows = {row["proposal_id"]: row for row in self._results(run)}
        self.assertEqual(set(rows), {proposal["proposal_id"] for proposal in proposals})
        first = rows[proposals[0]["proposal_id"]]
        self.assertEqual((first["parent_trial_id"], first["proposal_id"]),
                         (trials[0]["trial_id"], proposals[0]["proposal_id"]))
        self.assertTrue(first["confirmed"])
        self.assertEqual(first["confirm_k"], 3)
        self.assertIsNotNone(first["confirmation_run_dirs"])
        for proposal in proposals[1:]:
            self.assertIsNone(rows[proposal["proposal_id"]]["confirmation_alt_passes"])
            self.assertFalse((run / "ideation" / proposal["proposal_id"] / "confirm").exists())

    def test_arm_dir_refuses_a_different_model_task_or_parent(self):
        run, trials = self._run()
        proposal = self._proposal(trials[0], 0, "guard")
        base_cfg, recorded = self._arm_inputs(run, proposal)
        executor = rn.FixtureExecutor({})
        idn._arm(run, base_cfg, proposal, "select", True, executor, 2, None, recorded)
        calls = len(executor.calls)
        plan_path = run / "ideation" / proposal["proposal_id"] / "select" / "plan.json"
        original = plan_path.read_text(encoding="utf-8")
        other_model = dict(proposal, model="gemini-4-carbon")
        with self.assertRaisesRegex(ValueError, r"\(model\)"):
            idn._arm(run, base_cfg, other_model, "select", True, executor, 2, None, recorded)
        other_task = dict(proposal, task="other-task")
        with self.assertRaisesRegex(ValueError, r"\(task\)"):
            idn._arm(run, base_cfg, other_task, "select", True, executor, 2, None, recorded)
        self.assertEqual(plan_path.read_text(encoding="utf-8"), original)
        self.assertEqual(len(executor.calls), calls)

        idn._arm(run, base_cfg, proposal, "confirm", True, executor, 2, None, recorded)
        confirm_plan = run / "ideation" / proposal["proposal_id"] / "confirm" / "plan.json"
        confirm_text = confirm_plan.read_text(encoding="utf-8")
        confirm_calls = len(executor.calls)
        other_parent = dict(proposal, parent_trial_id=trials[1]["trial_id"])
        with self.assertRaisesRegex(ValueError, r"\(parent_trial_id\)"):
            idn._arm(run, base_cfg, other_parent, "confirm", True, executor, 2, None, recorded)
        self.assertEqual(confirm_plan.read_text(encoding="utf-8"), confirm_text)
        self.assertEqual(len(executor.calls), confirm_calls)

    def test_arm_dir_same_identity_rerun_is_not_refused(self):
        run, trials = self._run()
        proposal = self._proposal(trials[0], 0, "again")
        base_cfg, recorded = self._arm_inputs(run, proposal)
        executor = rn.FixtureExecutor({})
        idn._arm(run, base_cfg, proposal, "select", True, executor, 2, None, recorded)
        plan_path = run / "ideation" / proposal["proposal_id"] / "select" / "plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        self.assertEqual(plan["parent_trial_id"], proposal["parent_trial_id"])
        calls = len(executor.calls)
        idn._arm(run, base_cfg, proposal, "select", True, executor, 2, None, recorded)
        self.assertEqual(len(executor.calls), calls)
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        self.assertEqual(plan["parent_trial_id"], proposal["parent_trial_id"])
        self.assertEqual(plan["config"]["models"], [proposal["model"]])
        self.assertEqual(plan["config"]["tasks"], [proposal["task"]])
        # The same patch on another failure shares the selection directory.
        other_parent = dict(proposal, parent_trial_id=trials[1]["trial_id"])
        idn._arm(run, base_cfg, other_parent, "select", True, executor, 2, None, recorded)
        self.assertEqual(len(executor.calls), calls)


class Estimate(unittest.TestCase):
    def test_confirmation_is_in_the_cost_estimate(self):
        est = rn.ideation_estimate(rn.FixtureExecutor({}, cost_per_trial=2.0), {OPUS: 1})
        self.assertEqual((est["selection_usd"], est["confirmation_usd"], est["total_usd"], est["confirm"],
                          est["confirm_k"]), (300.0, 600.0, 900.0, "all", 1))
        half = rn.ideation_estimate(rn.FixtureExecutor({}, cost_per_trial=2.0), {OPUS: 1}, candidate_fraction=0.2)
        self.assertEqual(half["confirmation_usd"], 120.0)
        # Three failures in one cell: selection is three, confirmation is one.
        one_cell = rn.ideation_estimate(rn.FixtureExecutor({}, cost_per_trial=2.0), {OPUS: 3},
                                        confirm="top", cells={OPUS: 1})
        self.assertEqual((one_cell["selection_usd"], one_cell["confirmation_usd"], one_cell["total_usd"],
                          one_cell["confirm"], one_cell["confirm_k"]), (900.0, 120.0, 1020.0, "top", 1))
        # Eight cells, twenty-four failures: eight confirmations, not twenty-four.
        eight = rn.ideation_estimate(rn.FixtureExecutor({}, cost_per_trial=2.0), {OPUS: 24},
                                     confirm="top", cells={OPUS: 8}, candidate_fraction=0.5)
        self.assertEqual((eight["selection_usd"], eight["confirmation_usd"]), (7200.0, 960.0))
        all_half = rn.ideation_estimate(rn.FixtureExecutor({}, cost_per_trial=2.0), {OPUS: 1}, candidate_fraction=0.5)
        self.assertEqual(all_half["confirmation_usd"], 300.0)
        with self.assertRaisesRegex(ValueError, "cell"):
            rn.ideation_estimate(rn.FixtureExecutor({}), {OPUS: 3}, confirm="top")
        with self.assertRaisesRegex(ValueError, "confirm"):
            rn.ideation_estimate(rn.FixtureExecutor({}), {OPUS: 1}, confirm="maybe")

    def test_top_confirmation_price_is_cells_times_k_times_2n(self):
        unit = 2.0
        n = rn.N_TRIALS
        three = rn.ideation_estimate(rn.FixtureExecutor({}, cost_per_trial=unit), {OPUS: 3},
                                     confirm="top", cells={OPUS: 1}, confirm_k=3)
        self.assertEqual(three["confirm_k"], 3)
        self.assertEqual(three["confirmation_usd"], 1 * 3 * 2 * n * unit)
        self.assertEqual(three["selection_usd"], 900.0)
        eight = rn.ideation_estimate(rn.FixtureExecutor({}, cost_per_trial=unit), {OPUS: 24},
                                     confirm="top", cells={OPUS: 8}, confirm_k=2, candidate_fraction=0.5)
        self.assertEqual(eight["confirmation_usd"], 8 * 2 * 2 * n * unit)
        self.assertEqual(eight["confirm_k"], 2)
        default = rn.ideation_estimate(rn.FixtureExecutor({}, cost_per_trial=unit), {OPUS: 3},
                                       confirm="top", cells={OPUS: 1})
        self.assertEqual((default["confirm_k"], default["confirmation_usd"]), (1, 1 * 1 * 2 * n * unit))


if __name__ == "__main__":
    unittest.main()
