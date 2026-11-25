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

    def test_route_truncated_is_an_infra_failure_not_a_fail(self):
        class Truncating(rn.FixtureExecutor):
            def run_trial(self, spec, run_dir):
                if spec.trial_index == 2:
                    return rn.TrialResult(status="route_truncated", passed=None, steps=1, error="finish stop, no tool call")
                return super().run_trial(spec, run_dir)
        self.run_with(Truncating({}), models=[OSS], tasks=["extract-elf"], max_rounds=1)
        rows = rn.read_rows(self.dir / "trials.jsonl")
        self.assertEqual((rows[2]["status"], rows[2]["passed"]), ("route_truncated", None))
        s = rn.read_rows(self.dir / "summary.jsonl")[0]
        self.assertEqual((s["completed"], s["fails"], s["errors"], s["route_truncated"], s["verdict"]),
                         (2, 2, 1, 1, "incomplete"))

    def test_route_repair_counts_per_cell(self):
        class Repaired(rn.FixtureExecutor):
            def run_trial(self, spec, run_dir):
                res = super().run_trial(spec, run_dir)
                if spec.trial_index < 2:
                    res.route_counts = {"model_calls": 5, "tool_call_turns": 4, "route_repairs": spec.trial_index + 1}
                return res
        self.run_with(Repaired({("extract-elf", OSS): 3}), models=[OSS], tasks=["extract-elf"], max_rounds=1)
        rows = rn.read_rows(self.dir / "trials.jsonl")
        self.assertEqual(rows[0]["route_counts"]["route_repairs"], 1)
        s = rn.read_rows(self.dir / "summary.jsonl")[0]
        self.assertEqual((s["model_calls"], s["tool_call_turns"], s["route_repairs"], s["route_repair_share"]), (10, 8, 3, 0.375))
        self.assertEqual((s["trials_with_route_repair"], s["passes_with_route_repair"], s["trials_without_route_counts"]),
                         (2, 2, 1))

    def test_upstream_4xx_label_commit_and_thinking_fields(self):
        setting = {"thinking": {"type": "adaptive"}, "output_config": {"effort": "high"}}

        class Mixed(rn.FixtureExecutor):
            def run_trial(self, spec, run_dir):
                if spec.trial_index == 0:
                    return rn.TrialResult(status="upstream_4xx", passed=None, error="model call 3 returned 429")
                res = super().run_trial(spec, run_dir)
                res.thinking_setting, res.thinking_tokens_per_step = setting, [120, None]
                return res
        self.run_with(Mixed({}), models=[OPUS], tasks=["extract-elf"], max_rounds=1, suite_label="repo pilot suite")
        rows = rn.read_rows(self.dir / "trials.jsonl")
        self.assertEqual((rows[0]["status"], rows[0]["passed"]), ("upstream_4xx", None))
        self.assertEqual((rows[1]["thinking_setting"], rows[1]["thinking_tokens_per_step"]), (setting, [120, None]))
        self.assertTrue(all(r["suite_label"] == "repo pilot suite" and re.fullmatch(r"[0-9a-f]{40}", r["code_commit"])
                            for r in rows))
        s = rn.read_rows(self.dir / "summary.jsonl")[0]
        self.assertEqual((s["upstream_4xx"], s["errors"], s["verdict"], s["suite_label"]), (1, 1, "incomplete", "repo pilot suite"))
        self.assertEqual(json.loads((self.dir / "verdicts.json").read_text())["suite_label"], "repo pilot suite")
        with self.assertRaisesRegex(rn.RunnerError, "suite_label"):  # never pooled into the same directory
            self.run_with(Mixed({}), models=[OPUS], tasks=["extract-elf"], max_rounds=1, suite_label=None)

    def test_retried_4xx_and_image_pin_fields(self):
        class Imaged(rn.FixtureExecutor):
            def run_trial(self, spec, run_dir):
                res = super().run_trial(spec, run_dir)
                res.retried_4xx = {"429": 1} if spec.trial_index else {}
                res.image = {"ref": "openbench-tb2-x:pinned", "id": "sha256:" + "e" * 64, "pinned": "x@sha256:d",
                             "matches_pin": spec.trial_index != 1}
                return res
        self.run_with(Imaged({}), models=[OPUS], tasks=["extract-elf"], max_rounds=1)
        rows = rn.read_rows(self.dir / "trials.jsonl")
        self.assertEqual((rows[1]["retried_4xx"], rows[1]["image_id"], rows[1]["image_matches_pin"]),
                         ({"429": 1}, "sha256:" + "e" * 64, False))
        s = rn.read_rows(self.dir / "summary.jsonl")[0]
        self.assertEqual((s["retried_4xx"], s["image_matches_pin"], s["status_counts"] if "status_counts" in s else None),
                         ({"429": 2}, False, None))
        self.assertEqual(json.loads((self.dir / "verdicts.json").read_text())["models"][OPUS]["image_matches_pin_false"],
                         ["extract-elf"])

    def test_workers_give_the_same_results_and_swaps_as_one_at_a_time(self):
        import time
        passes = {("sanitize-git-repo", OPUS): 3, ("extract-elf", OPUS): 1, ("sanitize-git-repo", OSS): 0}

        class Slow(rn.FixtureExecutor):
            def run_trial(self, spec, run_dir):
                time.sleep(0.01 * (spec.trial_index % 3))   # finish out of order
                return super().run_trial(spec, run_dir)
        outcomes = []
        for workers in (1, 4):
            d = Path(tempfile.mkdtemp())
            rn.Runner(config(max_rounds=2), d, Slow(dict(passes)), workers=workers).run()
            rows = sorted((r["trial_id"], r["status"], r["passed"]) for r in rn.read_rows(d / "trials.jsonl"))
            swaps = {m: json.loads((d / "swaps" / f"{m}.json").read_text())["swaps"] for m in (OPUS, OSS)}
            outcomes.append((rows, swaps, json.loads((d / "verdicts.json").read_text())["models"]))
        self.assertEqual(outcomes[0], outcomes[1])
        self.assertTrue(outcomes[0][1][OPUS])  # sanitize-git-repo passed 3/3 for Opus and was swapped

    def test_cap_counts_running_trials(self):
        rn.Runner(config(models=[OPUS], tasks=["extract-elf"], n_trials=3, spend_cap_usd=0.025), self.dir,
                  rn.FixtureExecutor({}, cost_per_trial=0.01), workers=3).run()
        self.assertEqual(len(rn.read_rows(self.dir / "trials.jsonl")), 2)  # a 3rd would pass the cap with 2 running

    def test_provider_blocked_is_excluded_reported_and_never_swapped(self):
        class Blocked(rn.FixtureExecutor):
            def run_trial(self, spec, run_dir):
                if spec.task == "extract-elf":
                    return rn.TrialResult(status="provider_blocked", passed=None, cost_usd=0.0,
                                          provider_blocked={"blockReason": "SAFETY", "blockReasonMessage": "m"})
                return super().run_trial(spec, run_dir)
        rn.Runner(config(models=[OPUS], max_rounds=2), self.dir, Blocked({("sanitize-git-repo", OPUS): 3}), workers=2).run()
        s = {r["task"]: r for r in rn.read_rows(self.dir / "summary.jsonl")}["extract-elf"]
        self.assertEqual((s["verdict"], s["provider_blocked"], s["errors"], s["pass_rate"]), ("excluded", 3, 0, None))
        v = json.loads((self.dir / "verdicts.json").read_text())["models"][OPUS]
        self.assertEqual((v["excluded"], v["provider_blocked"]), (["extract-elf"], ["extract-elf"]))
        self.assertIn("extract-elf", v["current_suite"])  # no swap for a blocked task
        swaps = json.loads((self.dir / "swaps" / f"{OPUS}.json").read_text())["swaps"]
        self.assertEqual([x["from"] for x in swaps], ["sanitize-git-repo"])  # only the real pass swapped
        table = json.loads((self.dir / "provider_blocked.json").read_text())["models"][OPUS]["extract-elf"]
        self.assertEqual((table["trials_blocked"], table["trials"], table["block_reasons"], table["block_reason_messages"]),
                         (3, 3, {"SAFETY": 3}, ["m"]))

    def test_set_aside_trials_leave_the_denominator_with_an_all_fail_check(self):
        class Mixed(rn.FixtureExecutor):
            def run_trial(self, spec, run_dir):
                if spec.task == "extract-elf":
                    return rn.TrialResult(status="model_refused", passed=None, checker_exit=1,
                                          model_refused={"stop_reason": "refusal", "step": 4, "call_index": 4,
                                                         "stop_details": {"category": "bio"}})
                if spec.trial_index == 0:
                    return rn.TrialResult(status="provider_blocked", passed=None, provider_blocked={"blockReason": "SAFETY"})
                return super().run_trial(spec, run_dir)
        self.run_with(Mixed({("sanitize-git-repo", OPUS): 3}), models=[OPUS], max_rounds=1)
        s = {r["task"]: r for r in rn.read_rows(self.dir / "summary.jsonl")}
        sgr, elf = s["sanitize-git-repo"], s["extract-elf"]
        # 1 blocked + 2 completed passes: pass over the 2 completed; the all-fail check counts the block as a fail
        self.assertEqual((sgr["verdict"], sgr["pass_rate"], sgr["errors"], sgr["set_aside"]), ("pass", 1.0, 0, 1))
        self.assertEqual((sgr["verdict_all_fail"], sgr["pass_rate_all_fail"]), ("fail", 0.6667))
        self.assertEqual((elf["verdict"], elf["model_refused"], elf["verdict_all_fail"]), ("excluded", 3, "fail"))
        table = json.loads((self.dir / "set_aside.json").read_text())["models"][OPUS]
        self.assertEqual((table["extract-elf"]["model_refused"], table["extract-elf"]["refusals"][0]["step"]), (3, 4))
        self.assertEqual(table["sanitize-git-repo"]["provider_blocked"], 1)
        v = json.loads((self.dir / "verdicts.json").read_text())["models"][OPUS]
        self.assertEqual((v["excluded"], v["model_refused"], v["provider_blocked"]),
                         (["extract-elf"], ["extract-elf"], ["sanitize-git-repo"]))

    def test_timeout_while_working_is_a_fail_in_the_denominator(self):
        class Slow(rn.FixtureExecutor):
            def run_trial(self, spec, run_dir):
                if spec.trial_index == 0:
                    return rn.TrialResult(status="completed", passed=False, checker_exit=1, timed_out=True,
                                          timeout_detail={"cap_seconds": 1800, "still_working": True}, cost_usd=0.5)
                if spec.trial_index == 1:
                    return rn.TrialResult(status="timeout", passed=None, timed_out=True,
                                          timeout_detail={"cap_seconds": 1800, "still_working": False}, cost_usd=0.2)
                return super().run_trial(spec, run_dir)
        self.run_with(Slow({("extract-elf", OPUS): 3}), models=[OPUS], tasks=["extract-elf"], max_rounds=1)
        s = rn.read_rows(self.dir / "summary.jsonl")[0]
        self.assertEqual((s["completed"], s["fails"], s["errors"], s["timed_out"], s["timeout_fails"]), (2, 1, 1, 2, 1))
        rows = rn.read_rows(self.dir / "trials.jsonl")
        self.assertTrue(all("wall_seconds" in r and "host_load" in r for r in rows))
        self.assertEqual((rows[0]["timed_out"], rows[0]["cost_usd"]), (True, 0.5))

    def test_agent_exit_pending_tool_is_infra(self):
        class Exits(rn.FixtureExecutor):
            def run_trial(self, spec, run_dir):
                if spec.trial_index == 0:
                    return rn.TrialResult(status="agent_exit_pending_tool", passed=None,
                                          agent_exit={"last_finish": "tool-calls", "permission_rejected": []})
                return super().run_trial(spec, run_dir)
        self.run_with(Exits({}), models=[OPUS], tasks=["extract-elf"], max_rounds=1)
        s = rn.read_rows(self.dir / "summary.jsonl")[0]
        self.assertEqual((s["verdict"], s["agent_exit_pending_tool"], s["errors"]), ("incomplete", 1, 1))

    def test_side_thinking_signature_counts_as_infra_and_not_a_task_fail(self):
        class Exits(rn.FixtureExecutor):
            def run_trial(self, spec, run_dir):
                if spec.trial_index == 0:
                    return rn.TrialResult(status="side_thinking_signature", passed=False,
                                          env_cause="vertex_thinking_signature", signature_400s=1,
                                          side_kinds={"compaction": 1},
                                          side_signature={"side_kind": "compaction"},
                                          thinking_block_binding="off")
                return super().run_trial(spec, run_dir)
        self.run_with(Exits({("extract-elf", OPUS): 3}), models=[OPUS], tasks=["extract-elf"], max_rounds=1)
        s = rn.read_rows(self.dir / "summary.jsonl")[0]
        row = next(r for r in rn.read_rows(self.dir / "trials.jsonl") if r["trial_index"] == 0)
        # passed=False on the executor result is dropped: only completed trials have a verdict.
        self.assertEqual((row["status"], row["passed"], row["env_cause"], row["signature_400s"]),
                         ("side_thinking_signature", None, "vertex_thinking_signature", 1))
        self.assertEqual((s["verdict"], s["side_thinking_signature"], s["signature_400s"], s["errors"],
                          s["agent_exit_pending_tool"]), ("incomplete", 1, 1, 1, 0))
        self.assertEqual(s["post_compaction_signature"], 0)
        self.assertEqual(row["stripped_side_thinking_blocks"], 0)
        self.assertIsNone(row["post_compaction"])
        self.assertFalse(row["smoke_compaction"]["enabled"])

    def test_post_compaction_signature_counts_as_infra_and_not_a_task_fail(self):
        class Exits(rn.FixtureExecutor):
            def run_trial(self, spec, run_dir):
                if spec.trial_index == 0:
                    return rn.TrialResult(status="post_compaction_signature", passed=False,
                                          env_cause="vertex_thinking_signature", signature_400s=1,
                                          side_kinds={"compaction": 1},
                                          post_compaction={"prior_side_kind": "compaction"},
                                          stripped_side_thinking_blocks=2)
                return super().run_trial(spec, run_dir)
        self.run_with(Exits({("extract-elf", OPUS): 3}), models=[OPUS], tasks=["extract-elf"], max_rounds=1)
        s = rn.read_rows(self.dir / "summary.jsonl")[0]
        row = next(r for r in rn.read_rows(self.dir / "trials.jsonl") if r["trial_index"] == 0)
        self.assertEqual((row["status"], row["passed"], row["env_cause"], row["stripped_side_thinking_blocks"]),
                         ("post_compaction_signature", None, "vertex_thinking_signature", 2))
        self.assertEqual((s["verdict"], s["post_compaction_signature"], s["stripped_side_thinking_blocks"],
                          s["errors"], s["upstream_4xx"], s["side_thinking_signature"],
                          s["agent_exit_pending_tool"]), ("incomplete", 1, 2, 1, 0, 0, 0))

    def test_smoke_compaction_is_recorded_and_not_resumed_into_a_normal_run(self):
        self.run_with(rn.FixtureExecutor({("extract-elf", OPUS): 1}), models=[OPUS], tasks=["extract-elf"],
                      n_trials=1, max_rounds=1, smoke_compaction=True)
        plan = json.loads((self.dir / "plan.json").read_text())
        row = rn.read_rows(self.dir / "trials.jsonl")[0]
        self.assertTrue(plan["config"]["smoke_compaction"])
        self.assertTrue(plan["smoke_compaction"]["enabled"])
        self.assertEqual(plan["smoke_compaction"]["context_limit"], 72000)
        self.assertEqual(row["smoke_compaction"]["context_limit"], 72000)
        self.assertEqual(row["smoke_compaction"]["usable_tokens"], 40000)
        with self.assertRaisesRegex(rn.RunnerError, "smoke_compaction"):
            rn.Runner(config(models=[OPUS], tasks=["extract-elf"], n_trials=1, max_rounds=1,
                             smoke_compaction=False),
                      self.dir, rn.FixtureExecutor({})).run()

    def test_isolation_probe_gates_the_run_and_is_recorded(self):
        class Probed(rn.FixtureExecutor):
            result = {"ok": True, "networks": {"openbench-agent": {"metadata_reachable": False}}}

            def isolation_preflight(self):
                if not self.result["ok"]:
                    raise RuntimeError("isolation preflight failed: metadata reachable")
                return self.result
        runner, _ = self.run_with(Probed({}), models=[OPUS], tasks=["extract-elf"], max_rounds=1)
        self.assertEqual(json.loads((self.dir / "plan.json").read_text())["isolation"]["ok"], True)
        bad = Probed({})
        bad.result = {"ok": False}
        d = Path(tempfile.mkdtemp())
        with self.assertRaisesRegex(RuntimeError, "metadata reachable"):
            rn.Runner(config(models=[OPUS], tasks=["extract-elf"], max_rounds=1), d, bad).run()
        self.assertEqual((bad.calls, (d / "trials.jsonl").exists()), ([], False))  # nothing ran

    def test_workers_are_fixed_recorded_and_models_interleave(self):
        runner = rn.Runner(config(models=[CARBON, OPUS], tasks=["extract-elf"], max_rounds=1), self.dir,
                           rn.FixtureExecutor({}), workers=3)
        self.assertEqual([s.model for s in runner.plan({CARBON: ["extract-elf"], OPUS: ["extract-elf"]})][:4],
                         [CARBON, OPUS, CARBON, OPUS])
        runner.run()
        rows = rn.read_rows(self.dir / "trials.jsonl")
        self.assertTrue(all(r["workers"] == 3 and r["wall_seconds"] >= 0 and "cpus" in r["host_load"] for r in rows))
        self.assertEqual(json.loads((self.dir / "plan.json").read_text())["config"]["workers"], 3)
        with self.assertRaisesRegex(rn.RunnerError, "workers=3"):
            rn.Runner(config(models=[CARBON, OPUS], tasks=["extract-elf"], max_rounds=1), self.dir,
                      rn.FixtureExecutor({}), workers=8).run()

    def test_suite_label_rules(self):
        with self.assertRaisesRegex(rn.RunnerError, "unknown suite_label"):
            config(suite_label="pilot-ish")
        with self.assertRaisesRegex(rn.RunnerError, "allows suites"):
            config(suite="pilot-pool", suite_label="repo pilot suite")
        with patch.object(rn, "_is_imported", lambda task: task.id == "extract-elf"):
            with self.assertRaisesRegex(rn.RunnerError, "excludes imported tasks: \\['extract-elf'\\]"):
                rn.Runner(config(suite_label="repo pilot suite"), self.dir, rn.FixtureExecutor({}))

    def test_model_subset_runs_only_those_models(self):
        self.run_with(rn.FixtureExecutor({}), models=[CARBON, OPUS], tasks=["extract-elf"], max_rounds=1)
        self.assertEqual({r["model"] for r in rn.read_rows(self.dir / "trials.jsonl")}, {CARBON, OPUS})
        self.assertEqual(set(json.loads((self.dir / "verdicts.json").read_text())["models"]), {CARBON, OPUS})

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
                      for name in re.findall(r"`([a-z0-9_]+)`", line)}
        self.assertEqual(set(row), documented)
        summary = rn.read_rows(d / "summary.jsonl")[0]
        summary_doc = text.split("## Summary row", 1)[1].split("\n## ", 1)[0]
        documented = {name for line in re.findall(r"^\| ([^|]+) \|", summary_doc, re.M)
                      for name in re.findall(r"`([a-z0-9_]+)`", line)}
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
