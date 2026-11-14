"""SEA-107: the reflection-loop N-trial runner (obench/reflection/runner.py).
Offline: FixtureExecutor stands in for the containerized cell executor."""

from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from obench.hardsuite import config as hs_config
from obench.reflection import runner as rn
from obench.reflection import vertex_models as vm

DOC = Path(rn.__file__).with_name("RUNNER_TABLES.md")
OPUS, OSS, CARBON = "claude-opus-5-5", "gpt-oss-120b", "gemini-4-carbon"


def config(**over):
    raw = {"run_id": "dry", "suite": "pilot", "models": [OPUS, OSS], "n_trials": 3,
           "tasks": ["sanitize-git-repo", "extract-elf"]}
    raw.update(over)
    return rn.RunConfig.from_dict(raw)


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        p = patch.dict(os.environ, {hs_config.CUTOFF_ENV: ""})
        p.start()
        self.addCleanup(p.stop)

    def run_with(self, executor, **over):
        runner = rn.Runner(config(**over), self.dir, executor)
        return runner, runner.run()


class Config(unittest.TestCase):
    def test_default_n_is_30_and_models_are_the_three(self):
        cfg = rn.RunConfig.from_dict({"run_id": "r", "suite": "pilot", "models": [CARBON, OPUS, OSS]})
        self.assertEqual(cfg.n_trials, rn.N_TRIALS)
        self.assertEqual(rn.N_TRIALS, 30)
        self.assertEqual(cfg.alert_thresholds_usd, (5000.0, 10000.0, 15000.0))

    def test_bad_configs_are_refused(self):
        for raw in ({"run_id": "r", "suite": "pilot", "models": ["claude-sonnet-5-5"]},
                    {"run_id": "r", "suite": "pilot", "models": []},
                    {"run_id": "r", "suite": "pilot", "models": [OPUS], "n_trials": 0},
                    {"run_id": "a/b", "suite": "pilot", "models": [OPUS]},
                    {"run_id": "r", "suite": "pilot", "models": [OPUS], "surprise": 1},
                    {"run_id": "r", "suite": "pilot", "models": [OPUS], "patch_id": "p"}):
            with self.subTest(raw=raw), self.assertRaises((rn.RunnerError, vm.UnknownModel)):
                rn.RunConfig.from_dict(raw)

    def test_trial_ids_are_deterministic_and_attributable(self):
        a = rn.trial_id("run", "t", OPUS, None, 4)
        self.assertEqual(a, rn.trial_id("run", "t", OPUS, None, 4))
        self.assertEqual(len({a, rn.trial_id("run", "t", OPUS, None, 5), rn.trial_id("run", "t", OSS, None, 4),
                              rn.trial_id("run", "t", OPUS, "p1", 4)}), 4)


class Tables(Base):
    def test_rows_summary_verdicts_and_per_model_swap(self):
        executor = rn.FixtureExecutor({("sanitize-git-repo", OPUS): 3, ("extract-elf", OPUS): 1}, cost_per_trial=0.5)
        runner, status = self.run_with(executor)
        self.assertEqual(status["state"], "done")
        trials = rn.read_rows(self.dir / "trials.jsonl")
        self.assertEqual(len(trials), 2 * 2 * 3 + 3)  # round 1, then Opus's swapped-in task
        row = trials[0]
        for key in ("trial_id", "task", "bench", "bench_commit", "model", "vertex_id", "trial_index", "status",
                    "passed", "cost_usd", "thinking_tokens", "trace", "price_verified"):
            self.assertIn(key, row)
        summary = {(s["task"], s["model"]): s for s in rn.read_rows(self.dir / "summary.jsonl")}
        s = summary[("sanitize-git-repo", OPUS)]
        self.assertEqual((s["passes"], s["fails"], s["pass_rate"], s["verdict"], s["cutoff"]), (3, 0, 1.0, "pass", 0.9))
        self.assertEqual((s["spend_usd"], s["thinking_tokens_total"]), (1.5, 30))
        self.assertEqual(s["traces"], "trials/claude-opus-5-5/sanitize-git-repo/*/trace.jsonl")
        self.assertEqual(summary[("extract-elf", OPUS)]["verdict"], "fail")
        verdicts = json.loads((self.dir / "verdicts.json").read_text())
        self.assertEqual(verdicts["models"][OPUS]["pass"], ["sanitize-git-repo"])
        # Harder swap for Opus only; gpt-oss keeps the original.
        self.assertIn("polyglot-c-py", verdicts["models"][OPUS]["current_suite"])
        self.assertNotIn("sanitize-git-repo", verdicts["models"][OPUS]["current_suite"])
        self.assertIn("sanitize-git-repo", verdicts["models"][OSS]["current_suite"])
        self.assertEqual(summary[("polyglot-c-py", OPUS)]["trials"], 3)
        self.assertNotIn(("polyglot-c-py", OSS), summary)

    def test_paths_in_rows_are_relative(self):
        self.run_with(rn.FixtureExecutor({}))
        for row in rn.read_rows(self.dir / "trials.jsonl"):
            for key in ("trace", "trial_dir"):
                self.assertFalse(str(row[key]).startswith("/"), row[key])
                self.assertTrue((self.dir / row[key]).exists())
        text = (self.dir / "trials.jsonl").read_text() + (self.dir / "summary.jsonl").read_text()
        self.assertNotIn(str(self.dir), text)

    def test_cutoff_comes_from_the_single_constant(self):
        executor = rn.FixtureExecutor({("sanitize-git-repo", OPUS): 2})  # 2/3 = 0.67
        with patch.dict(os.environ, {hs_config.CUTOFF_ENV: "0.6"}):
            runner, _ = self.run_with(executor, models=[OPUS], tasks=["sanitize-git-repo"], max_rounds=1)
        summary = rn.read_rows(self.dir / "summary.jsonl")[0]
        self.assertEqual((summary["cutoff"], summary["verdict"]), (0.6, "pass"))
        self.assertEqual(json.loads((self.dir / "plan.json").read_text())["cutoff"], 0.6)
        source = Path(rn.__file__).read_text()
        self.assertNotRegex(source, r"\b0\.9[05]?\b")  # no second copy of the cutoff

    def test_errors_make_a_group_incomplete_and_never_swap(self):
        executor = rn.FixtureExecutor({("sanitize-git-repo", OPUS): 3}, errors={("sanitize-git-repo", OPUS): {1}})
        self.run_with(executor, models=[OPUS], tasks=["sanitize-git-repo"])
        s = rn.read_rows(self.dir / "summary.jsonl")[0]
        self.assertEqual((s["completed"], s["errors"], s["verdict"]), (2, 1, "incomplete"))
        verdicts = json.loads((self.dir / "verdicts.json").read_text())
        self.assertIn("sanitize-git-repo", verdicts["models"][OPUS]["current_suite"])

    def test_executor_crash_and_wrong_model_are_recorded(self):
        class Bad(rn.FixtureExecutor):
            def run_trial(self, spec, run_dir):
                if spec.trial_index == 0:
                    raise RuntimeError("container died")
                res = super().run_trial(spec, run_dir)
                res.served_models = ["claude-sonnet-5-5"]
                return res
        self.run_with(Bad({}), models=[OPUS], tasks=["extract-elf"], max_rounds=1)
        rows = rn.read_rows(self.dir / "trials.jsonl")
        self.assertEqual((rows[0]["status"], rows[0]["error"]), ("error", "RuntimeError: container died"))
        self.assertEqual(rows[1]["wrong_model_served"], ["claude-sonnet-5-5"])
        self.assertEqual(rn.read_rows(self.dir / "summary.jsonl")[0]["wrong_model_trials"], 2)

    def test_gpt_oss_body_model_form_is_not_a_wrong_model(self):
        class OssServed(rn.FixtureExecutor):
            def run_trial(self, spec, run_dir):
                res = super().run_trial(spec, run_dir)
                res.served_models = ["openai/gpt-oss-120b-maas"]
                return res
        self.run_with(OssServed({}), models=[OSS], tasks=["extract-elf"], max_rounds=1)
        rows = rn.read_rows(self.dir / "trials.jsonl")
        self.assertTrue(all(r["wrong_model_served"] == [] for r in rows))

    def test_resume_skips_trials_already_written(self):
        executor = rn.FixtureExecutor({})
        self.run_with(executor, models=[OPUS], tasks=["extract-elf"])
        again = rn.FixtureExecutor({})
        _, status = self.run_with(again, models=[OPUS], tasks=["extract-elf"])
        self.assertEqual((again.calls, status["state"]), ([], "done"))
        self.assertEqual(len(rn.read_rows(self.dir / "trials.jsonl")), 3)


class Spend(Base):
    def test_preflight_estimate_and_cap(self):
        runner = rn.Runner(config(spend_cap_usd=1.0), self.dir, rn.FixtureExecutor({}, cost_per_trial=0.25))
        pre = runner.preflight()
        self.assertEqual((pre["trials_round_one"], pre["round_one_usd"], pre["within_cap"]), (12, 3.0, False))
        self.assertEqual(pre["worst_case_usd"], 9.0)
        status = runner.run()
        self.assertEqual(status["state"], "capped")
        self.assertEqual(len(rn.read_rows(self.dir / "trials.jsonl")), 4)  # 4 x $0.25 = the cap
        self.assertLessEqual(status["spent_usd"], 1.0)

    def test_alert_threshold_pauses_until_acknowledged(self):
        executor = rn.FixtureExecutor({}, cost_per_trial=1.0)
        runner, status = self.run_with(executor, models=[OPUS], tasks=["extract-elf"], alert_thresholds_usd=[2.0])
        self.assertEqual((status["state"], status["threshold_usd"]), ("alert", 2.0))
        self.assertEqual(len(rn.read_rows(self.dir / "trials.jsonl")), 2)
        status = rn.Runner(config(models=[OPUS], tasks=["extract-elf"], alert_thresholds_usd=[2.0]), self.dir,
                           executor).run(acknowledge_alerts=(2.0,))
        self.assertEqual(status["state"], "done")
        self.assertEqual(len(rn.read_rows(self.dir / "trials.jsonl")), 3)

    def test_patch_runs_never_swap(self):
        executor = rn.FixtureExecutor({("extract-elf", OPUS): 3})
        self.run_with(executor, models=[OPUS], tasks=["extract-elf"], patch_id="p1", patch={"ops": []})
        verdicts = json.loads((self.dir / "verdicts.json").read_text())
        self.assertIn("extract-elf", verdicts["models"][OPUS]["current_suite"])
        self.assertTrue(all(c.patch_id == "p1" for c in executor.calls))


class Doc(unittest.TestCase):
    def test_documented_fields_match_rows(self):
        text = DOC.read_text()
        d = Path(tempfile.mkdtemp())
        with patch.dict(os.environ, {hs_config.CUTOFF_ENV: ""}):
            rn.Runner(config(models=[OPUS], tasks=["extract-elf"], max_rounds=1), d, rn.FixtureExecutor({})).run()
        row = rn.read_rows(d / "trials.jsonl")[0]
        trial_doc = text.split("## Trial row", 1)[1].split("\n## ", 1)[0]
        documented = {name for line in re.findall(r"^\| ([^|]+) \|", trial_doc, re.M)
                      for name in re.findall(r"`([a-z_]+)`", line)}
        self.assertEqual(set(row), documented)
        summary = rn.read_rows(d / "summary.jsonl")[0]
        summary_doc = text.split("## Summary row", 1)[1].split("\n## ", 1)[0]
        documented = {name for line in re.findall(r"^\| ([^|]+) \|", summary_doc, re.M)
                      for name in re.findall(r"`([a-z_]+)`", line)}
        self.assertEqual(set(summary) - {"schema", "run_id"}, documented)

    def test_cli_dry_run(self):
        d = Path(tempfile.mkdtemp())
        cfg, fx = d / "cfg.json", d / "fx.json"
        cfg.write_text(json.dumps({"run_id": "cli", "suite": "pilot", "models": [OPUS], "n_trials": 2,
                                   "tasks": ["extract-elf"], "max_rounds": 1}))
        fx.write_text(json.dumps({f"extract-elf|{OPUS}": 2}))
        with patch.dict(os.environ, {hs_config.CUTOFF_ENV: ""}):
            self.assertEqual(rn.main(["--config", str(cfg), "--out", str(d / "run"), "--fixture", str(fx)]), 0)
        self.assertEqual(rn.read_rows(d / "run" / "summary.jsonl")[0]["verdict"], "pass")
        with self.assertRaises(SystemExit):
            rn.main(["--config", str(cfg), "--out", str(d / "run")])  # no executor chosen


if __name__ == "__main__":
    unittest.main()
