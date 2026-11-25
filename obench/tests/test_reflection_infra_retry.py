"""Resume re-runs infrastructure-error trials. The swap rule is not modified."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from obench.hardsuite import config as hs_config
from obench.hardsuite import swap
from obench.hardsuite.suite import load_suite
from obench.reflection import runner as rn
from obench.reflection.wire_proxy import last_vertex_request

OPUS, OSS, CARBON = "claude-opus-5-5", "gpt-oss-120b", "gemini-4-carbon"


def config(**over):
    raw = {"run_id": "dry", "suite": "pilot", "models": [OPUS], "n_trials": 3,
           "tasks": ["extract-elf"], "max_rounds": 1}
    raw.update(over)
    return rn.RunConfig.from_dict(raw)


def _last(arrived=True):
    return {"sent_at": "2026-11-17T00:00:00+00:00", "model": OPUS, "response_arrived": arrived,
            "first_byte_at": "2026-11-17T00:00:01+00:00" if arrived else None,
            "call_index": 1, "status": 200 if arrived else None}


class Scripted(rn.FixtureExecutor):
    """``outcomes[(attempt, trial_index)]`` overrides the pass table. Every result carries a last Vertex request."""

    def __init__(self, passes, outcomes=None, **kw):
        super().__init__(passes, **kw)
        self.outcomes = outcomes or {}

    def run_trial(self, spec, run_dir):
        spec_outcome = self.outcomes.get((spec.attempt, spec.trial_index))
        if spec_outcome == "timeout":
            self.calls.append(spec)
            return rn.TrialResult(status="timeout", passed=None, timed_out=True, cost_usd=self.cost,
                                  timeout_detail={"cap_seconds": 1800, "still_working": False,
                                                   "last_call_ended_before_cap_s": 400},
                                  last_vertex_request=_last(False), error="infra timeout")
        if spec_outcome == "working":
            return rn.TrialResult(status="completed", passed=False, checker_exit=1, timed_out=True, cost_usd=self.cost,
                                  timeout_detail={"cap_seconds": 1800, "still_working": True,
                                                   "last_call_ended_before_cap_s": 10},
                                  last_vertex_request=_last(True))
        if spec_outcome == "refused":
            return rn.TrialResult(status="model_refused", passed=None, cost_usd=self.cost,
                                  model_refused={"stop_reason": "refusal", "step": 1},
                                  last_vertex_request=_last(True))
        if spec_outcome == "error":
            return rn.TrialResult(status="error", passed=None, cost_usd=self.cost, error="boom",
                                  last_vertex_request=_last(False))
        result = super().run_trial(spec, run_dir)
        result.last_vertex_request = _last(True)
        return result


class InfraRetry(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        env = patch.dict(os.environ, {hs_config.CUTOFF_ENV: ""})
        env.start()
        self.addCleanup(env.stop)

    def _run(self, executor, retry_infra=False, **over):
        runner = rn.Runner(config(**over), self.dir, executor)
        return runner, runner.run(retry_infra=retry_infra)

    def test_infra_set_is_everything_but_settled(self):
        self.assertEqual(rn.SETTLED_STATUSES, ("completed", "provider_blocked", "model_refused"))
        self.assertEqual(rn.INFRA_STATUSES, ("error", "timeout", "route_truncated", "upstream_4xx",
                                             "agent_exit_pending_tool", "side_thinking_signature", "checker_error"))
        self.assertEqual(rn.MAX_INFRA_RETRIES, 3)

    def test_resume_reruns_only_the_infra_slot_then_the_unchanged_swap_rule_fires(self):
        # 29 passes + 1 infra timeout. No swap until the re-run settles the cell at 30/30.
        passes = {("sanitize-git-repo", OPUS): 30}
        outcomes = {(0, 29): "timeout"}
        first = Scripted(passes, outcomes)
        self._run(first, models=[OPUS], tasks=["sanitize-git-repo"], n_trials=30, max_rounds=1)
        summary = rn.read_rows(self.dir / "summary.jsonl")[0]
        self.assertEqual((summary["passes"], summary["completed"], summary["verdict"]), (29, 29, "incomplete"))
        self.assertEqual(json.loads((self.dir / "swaps" / f"{OPUS}.json").read_text())["swaps"], [])
        original = next(r for r in rn.read_rows(self.dir / "trials.jsonl") if r["trial_index"] == 29)
        original_line = json.dumps(original, sort_keys=True)
        self.assertIsNone(original["retry_of"])
        self.assertFalse(original["last_vertex_request"]["response_arrived"])
        # A pass row (not a retry) also logged the last Vertex request.
        passed = next(r for r in rn.read_rows(self.dir / "trials.jsonl") if r["trial_index"] == 0)
        self.assertTrue(passed["last_vertex_request"]["response_arrived"])
        self.assertEqual(passed["last_vertex_request"]["sent_at"], "2026-11-17T00:00:00+00:00")

        report = rn.Runner(config(models=[OPUS], tasks=["sanitize-git-repo"], n_trials=30, max_rounds=1),
                           self.dir, rn.FixtureExecutor({})).infra_retry_report()
        cell = report["cells"][0]
        self.assertEqual((cell["settled"], cell["infra"], cell["would_rerun"]), (29, 1, 1))

        again = Scripted(passes, outcomes)  # attempt 0 index 29 would still time out; the re-run is attempt 1
        self._run(again, retry_infra=True, models=[OPUS], tasks=["sanitize-git-repo"], n_trials=30, max_rounds=1)
        self.assertEqual([(c.trial_index, c.attempt) for c in again.calls], [(29, 1)])
        rows = rn.read_rows(self.dir / "trials.jsonl")
        self.assertIn(original_line, (self.dir / "trials.jsonl").read_text())
        retry = next(r for r in rows if r["attempt"] == 1)
        self.assertEqual(retry["retry_of"], original["trial_id"])
        self.assertNotEqual(retry["trial_id"], original["trial_id"])
        self.assertTrue(retry["passed"])
        summary = rn.read_rows(self.dir / "summary.jsonl")[0]
        self.assertEqual((summary["passes"], summary["completed"], summary["verdict"]), (30, 30, "pass"))
        suite, pool = load_suite("pilot"), load_suite("pilot-pool")
        _state, expected = swap.apply_results(swap.initial_state(OPUS, suite),
                                              {"sanitize-git-repo": (30, 30)}, suite, pool)
        got = json.loads((self.dir / "swaps" / f"{OPUS}.json").read_text())["swaps"]
        self.assertEqual(got, expected)
        self.assertEqual((got[0]["from"], got[0]["successes"], got[0]["trials"]), ("sanitize-git-repo", 30, 30))

    def test_retry_cap_leaves_the_cell_incomplete_and_does_not_run_again(self):
        outcomes = {(attempt, 0): "timeout" for attempt in range(4)}
        self._run(Scripted({("extract-elf", OPUS): 2}, outcomes), models=[OPUS], tasks=["extract-elf"], n_trials=2)
        original = next(r for r in rn.read_rows(self.dir / "trials.jsonl") if r["trial_index"] == 0)
        original_line = json.dumps(original, sort_keys=True)
        again = Scripted({("extract-elf", OPUS): 2}, outcomes)
        _, status = self._run(again, retry_infra=True, models=[OPUS], tasks=["extract-elf"], n_trials=2)
        self.assertEqual(status["state"], "done")
        self.assertEqual([c.attempt for c in again.calls], [1, 2, 3])
        rows = [r for r in rn.read_rows(self.dir / "trials.jsonl") if r["trial_index"] == 0]
        self.assertEqual(len(rows), 4)  # original + 3 re-runs, none deleted
        self.assertTrue(all(r["retry_of"] == original["trial_id"] for r in rows if r["attempt"]))
        self.assertIn(original_line, (self.dir / "trials.jsonl").read_text())
        summary = rn.read_rows(self.dir / "summary.jsonl")[0]
        self.assertEqual(summary["verdict"], "incomplete")
        self.assertIn("trial_index 0 still timeout after 3 re-runs", summary["incomplete_reason"])
        self.assertEqual(summary["infra_retry_exhausted"][0]["retries"], 3)
        third = Scripted({("extract-elf", OPUS): 2}, outcomes)
        self._run(third, retry_infra=True, models=[OPUS], tasks=["extract-elf"], n_trials=2)
        self.assertEqual(third.calls, [])

    def test_settled_failures_and_refusals_are_not_retried(self):
        outcomes = {(0, 0): "working", (0, 1): "refused"}
        self._run(Scripted({}, outcomes), models=[OPUS], tasks=["extract-elf"], n_trials=2)
        again = Scripted({}, outcomes)
        self._run(again, retry_infra=True, models=[OPUS], tasks=["extract-elf"], n_trials=2)
        self.assertEqual(again.calls, [])
        summary = rn.read_rows(self.dir / "summary.jsonl")[0]
        # The still-working timeout is a completed fail and the refusal is set aside: both settled, so no re-run.
        self.assertEqual((summary["verdict"], summary["completed"], summary["model_refused"]), ("fail", 1, 1))

    def test_only_the_infra_row_is_retried_among_a_fail(self):
        outcomes = {(0, 0): "error"}
        self._run(Scripted({("extract-elf", OPUS): 0}, outcomes), n_trials=2)
        again = Scripted({("extract-elf", OPUS): 2}, {})  # the re-run passes; index 1 already failed and stays
        self._run(again, retry_infra=True, n_trials=2)
        self.assertEqual([(c.trial_index, c.attempt) for c in again.calls], [(0, 1)])

    def test_retries_follow_plan_order_across_models(self):
        outcomes = {(0, 0): "timeout"}
        passes = {}
        self._run(Scripted(passes, outcomes), models=[CARBON, OPUS], tasks=["extract-elf"], n_trials=2)
        runner = rn.Runner(config(models=[CARBON, OPUS], tasks=["extract-elf"], n_trials=2), self.dir, Scripted(passes, outcomes))
        specs = runner.pending_specs({CARBON: ["extract-elf"], OPUS: ["extract-elf"]}, True)
        self.assertEqual([(s.model, s.trial_index, s.attempt) for s in specs], [(CARBON, 0, 1), (OPUS, 0, 1)])
        runner.run(retry_infra=True)
        self.assertEqual([(c.model, c.attempt) for c in runner.executor.calls], [(CARBON, 1), (OPUS, 1)])

    def test_head_or_host_mismatch_is_refused(self):
        self._run(Scripted({}), n_trials=2)  # both fail: settled, and the slot does not swap
        plan_path = self.dir / "plan.json"
        plan = json.loads(plan_path.read_text())
        plan["code"]["commit"] = "a" * 40
        plan["host"] = "thesis-h1-cpu"
        plan_path.write_text(json.dumps(plan))
        runner = rn.Runner(config(n_trials=2), self.dir, Scripted({}))
        with self.assertRaisesRegex(rn.RunnerError, "git commit"):
            runner.run(retry_infra=True)
        self.assertEqual(runner.executor.calls, [])
        plan["code"]["commit"] = rn.code_commit()["commit"]
        plan_path.write_text(json.dumps(plan))
        with patch.object(rn, "host_name", return_value="other-host"):
            with self.assertRaisesRegex(rn.RunnerError, "host"):
                rn.Runner(config(n_trials=2), self.dir, Scripted({})).run(retry_infra=True)
        # Missing host is recorded, not refused. A differing commit is allowed only with the override,
        # and the recorded commit stays the plan's.
        plan.pop("host")
        plan["code"]["commit"] = "b" * 40
        plan_path.write_text(json.dumps(plan))
        allowed = Scripted({})
        rn.Runner(config(n_trials=2), self.dir, allowed).run(retry_infra=True, allow_plan_mismatch=True)
        self.assertEqual(allowed.calls, [])
        kept = json.loads(plan_path.read_text())
        self.assertEqual(kept["code"]["commit"], "b" * 40)
        self.assertEqual(kept["host"], rn.host_name())

    def test_dry_run_counts_and_does_not_run(self):
        outcomes = {(0, 1): "timeout"}
        self._run(Scripted({("extract-elf", OPUS): 2}, outcomes), n_trials=2)
        buf, err = StringIO(), StringIO()
        with redirect_stdout(buf), redirect_stderr(err):
            code = rn.main(["--resume", str(self.dir), "--retry-infra", "--dry-run"])
        self.assertEqual(code, 0)
        report = json.loads(buf.getvalue())
        self.assertEqual(report["cells"][0]["settled"], 1)
        self.assertEqual(report["cells"][0]["infra"], 1)
        self.assertEqual(report["cells"][0]["would_rerun"], 1)
        self.assertEqual(len(rn.read_rows(self.dir / "trials.jsonl")), 2)

    def test_spend_cap_still_stops_a_retry(self):
        outcomes = {(0, 1): "error"}
        self._run(Scripted({("extract-elf", OPUS): 1}, outcomes, cost_per_trial=1.0),
                  n_trials=2, spend_cap_usd=2.0)
        again = Scripted({("extract-elf", OPUS): 2}, {}, cost_per_trial=1.0)
        _, status = self._run(again, retry_infra=True, n_trials=2, spend_cap_usd=2.0)
        self.assertEqual((status["state"], again.calls), ("capped", []))

    def test_last_vertex_request_prefers_an_unfinished_call(self):
        wires = [{"call_index": 1, "ts": "t1", "requested_model": OPUS, "response_arrived": True,
                  "first_byte_at": "t1b", "status": 200}]
        live = {"sent_at": "t2", "model": OPUS, "response_arrived": False, "first_byte_at": None,
                "call_index": 2, "status": None}
        self.assertEqual(last_vertex_request(wires, live)["call_index"], 2)
        self.assertFalse(last_vertex_request(wires, live)["response_arrived"])
        self.assertTrue(last_vertex_request(wires, None)["response_arrived"])


if __name__ == "__main__":
    unittest.main()
