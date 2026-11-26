"""Spend caps, workers, arm lock, and checker runtime on the credit-assignment arms.

Offline stubs only. No network.
"""

from __future__ import annotations

import fcntl
import io
import json
import os
import threading
import unittest
import warnings
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from obench.hardsuite import config as hs_config
from obench.reflection import cell_executor as ce
from obench.reflection import credit_baseline as base
from obench.reflection import ideation as idn
from obench.reflection import patches as pt
from obench.reflection import runner as rn
from obench.tests.test_reflection_credit_baseline import (
    ELF, ELF_IMAGE, OPUS, QUERY, QUERY_IMAGE, _parent, _stamp,
)
from unittest.mock import patch as mock_patch


def _passes(task, n):
    return {(task, OPUS): n}


class Priced:
    """Fixture executor with a known per-trial price. Optional hold so launches overlap."""

    def __init__(self, passes=None, cost=1.0, hold=None, ready=None, ready_at=1):
        self.passes = passes or {}
        self.cost = cost
        self.hold = hold
        self.ready = ready
        self.ready_at = ready_at
        self.calls = []
        self.smoke_compaction = False
        self._lock = threading.Lock()
        self.inflight = 0
        self.peak = 0
        self.active_runs = set()
        self.peak_runs = 0

    def estimate_cost_usd(self, model):
        return self.cost

    def run_trial(self, spec, run_dir):
        with self._lock:
            self.calls.append(spec)
            self.inflight += 1
            self.peak = max(self.peak, self.inflight)
            self.active_runs.add(spec.run_id)
            self.peak_runs = max(self.peak_runs, len(self.active_runs))
            started = len(self.calls)
        if self.ready is not None and started >= self.ready_at:
            self.ready.set()
        if self.hold is not None:
            self.hold.wait(5)
        with self._lock:
            self.inflight -= 1
            if self.inflight == 0:
                self.active_runs.clear()
        trace = f"{spec.trial_dir}/trace.jsonl"
        path = Path(run_dir) / trace
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"step": 1}\n', encoding="utf-8")
        passed = spec.trial_index < self.passes.get((spec.task, spec.model), 0)
        return rn.TrialResult(status="completed", passed=passed, checker_exit=0 if passed else 1,
                              steps=1, cost_usd=self.cost, trace=trace)


def _two_cells():
    run = _parent()
    _stamp(run, {ELF: ELF_IMAGE, QUERY: QUERY_IMAGE})
    return run


def _proposal(task=ELF):
    patch = {"schema": pt.PATCH_SCHEMA, "ops": [{"op": "system_append", "text": "cap"}]}
    return {"schema": idn.PROPOSAL_SCHEMA, "status": "accepted", "uncited": False, "index": 0,
            "proposal_id": pt.patch_id(patch), "patch": patch, "parent_trial_id": "parent-1",
            "task": task, "model": OPUS, "credit_method": "A", "citations": []}


def _install_baseline(run: Path, task=ELF, workers=1, **extra):
    commit = rn.code_commit()["commit"]
    cell = f"{OPUS}/{task}"
    row = {
        "schema": "openbench.reflection.credit_baseline/v1", "cell": cell,
        "task": task, "model": OPUS, "passes": 0, "completed": 30, "set_aside": 0,
        "provider_blocked": 0, "model_refused": 0,
        "baseline_commit": commit, "code_commit": commit,
        "image": {"ref": "recorded:test", "id": "sha256:" + "11" * 32},
        "image_matches_pin": True,
    }
    if workers is not None:
        row["workers"] = workers
    row.update(extra)
    doc = {}
    path = run / "credit_baseline.json"
    if path.is_file():
        doc = json.loads(path.read_text(encoding="utf-8"))
    doc[cell] = row
    path.write_text(json.dumps(doc) + "\n", encoding="utf-8")


def _ideation_run():
    run = _parent((ELF,))
    _stamp(run, {ELF: ELF_IMAGE})
    _install_baseline(run)
    return run


class Caps(unittest.TestCase):
    def setUp(self):
        patcher = mock_patch.dict(os.environ, {hs_config.CUTOFF_ENV: ""})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_total_cap_stops_the_invocation_and_keeps_rows(self):
        run = _two_cells()
        stub = Priced(passes=_passes(ELF, 4) | _passes(QUERY, 4), cost=1.0)
        manifests = base.run_baselines(run, [f"{OPUS}/{ELF}", f"{OPUS}/{QUERY}"], stub,
                                       n_trials=4, max_usd=2.0)
        self.assertEqual(set(manifests), {f"{OPUS}/{ELF}"})
        elf = manifests[f"{OPUS}/{ELF}"]
        self.assertTrue(elf["stopped_by_cap"])
        self.assertEqual(elf["stop_reason"], "max_usd")
        self.assertEqual(elf["stop_cell"], f"{OPUS}/{ELF}")
        self.assertEqual(elf["trials_completed"], 2)
        rows = rn.read_rows(run / elf["run_dir"] / "trials.jsonl")
        self.assertEqual(len(rows), 2)
        self.assertLessEqual(sum(row["cost_usd"] for row in rows), 2.0)
        self.assertEqual({spec.task for spec in stub.calls}, {ELF})
        status = json.loads((run / elf["run_dir"] / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(status["stop_reason"], "max_usd")
        self.assertEqual(status["max_usd"], 2.0)

    def test_per_cell_cap_stops_only_that_cell(self):
        run = _two_cells()
        stub = Priced(passes=_passes(ELF, 4) | _passes(QUERY, 4), cost=1.0)
        manifests = base.run_baselines(run, [f"{OPUS}/{ELF}", f"{OPUS}/{QUERY}"], stub,
                                       n_trials=4, max_usd_per_cell=2.0)
        self.assertEqual(set(manifests), {f"{OPUS}/{ELF}", f"{OPUS}/{QUERY}"})
        for name, row in manifests.items():
            self.assertTrue(row["stopped_by_cap"], name)
            self.assertEqual(row["stop_reason"], "max_usd_per_cell")
            self.assertEqual(row["stop_cell"], name)
            self.assertEqual(row["trials_completed"], 2)
            trials = rn.read_rows(run / row["run_dir"] / "trials.jsonl")
            self.assertEqual(len(trials), 2)
            self.assertLessEqual(sum(trial["cost_usd"] for trial in trials), 2.0)
        self.assertEqual(len(stub.calls), 4)

    def test_resume_counts_prior_spend_once(self):
        run = _ideation_run()
        proposal = _proposal()
        (run / "ideation.jsonl").write_text(json.dumps(proposal) + "\n", encoding="utf-8")
        first = Priced(cost=1.0)
        row = idn.evaluate(run, proposal, first, n_trials=4, spend_cap_usd=2.0)
        self.assertEqual(row["trials_completed"], 2)
        ids = [spec.trial_id for spec in first.calls]
        self.assertEqual(len(ids), 2)
        again = Priced(cost=1.0)
        resumed = idn.evaluate(run, proposal, again, n_trials=4, spend_cap_usd=3.0)
        arm = run / row["selection_run_dir"] / "trials.jsonl"
        rows = rn.read_rows(arm)
        self.assertEqual(len(rows), 3)
        self.assertEqual(sum(item["cost_usd"] for item in rows), 3.0)
        self.assertEqual([item["trial_id"] for item in rows[:2]], ids)
        self.assertEqual(len(again.calls), 1)
        self.assertEqual(resumed["trials_completed"], 3)
        self.assertIsNone(resumed["candidate"])

    def test_a_cap_stop_does_not_replace_a_finished_baseline(self):
        run = _two_cells()
        first = base.run_baselines(run, [f"{OPUS}/{ELF}"], Priced(passes=_passes(ELF, 2), cost=0.01), n_trials=2)
        manifest = (run / "credit_baseline.json").read_text(encoding="utf-8")
        trials = (run / first[f"{OPUS}/{ELF}"]["run_dir"] / "trials.jsonl").read_text(encoding="utf-8")
        again = Priced(cost=1.0)
        kept = base.run_baselines(run, [f"{OPUS}/{ELF}"], again, n_trials=2, max_usd=0.5)
        self.assertEqual((run / "credit_baseline.json").read_text(encoding="utf-8"), manifest)
        self.assertEqual((run / kept[f"{OPUS}/{ELF}"]["run_dir"] / "trials.jsonl").read_text(encoding="utf-8"), trials)
        self.assertEqual(again.calls, [])
        stopped = run / "credit_baseline" / "runs" / f"{OPUS}__{ELF}.stopped"
        self.assertTrue((stopped / "status.json").is_file())
        status = json.loads((stopped / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(status["stop_reason"], "max_usd")

    def test_unset_caps_match_an_uncapped_runner(self):
        run = _two_cells()
        stub = Priced(passes=_passes(ELF, 2), cost=0.01)
        manifests = base.run_baselines(run, [f"{OPUS}/{ELF}"], stub, n_trials=2)
        elf = manifests[f"{OPUS}/{ELF}"]
        self.assertNotIn("stopped_by_cap", elf)
        self.assertEqual(elf["passes"], 2)
        direct = Path(run) / "direct"
        cfg = rn.RunConfig.from_dict({
            "run_id": f"pilot--baseline--{OPUS}__{ELF}", "suite": "pilot", "models": [OPUS],
            "n_trials": 2, "tasks": [ELF], "max_rounds": 1, "fixed_tasks": True,
            "smoke_compaction": False, "recorded_image": ELF_IMAGE, "workers": 1,
        })
        rn.Runner(cfg, direct, Priced(passes=_passes(ELF, 2), cost=0.01)).run()
        skip = {"started_at", "finished_at", "wall_seconds", "host_load"}

        def stable(path):
            return [{key: row[key] for key in row if key not in skip}
                    for row in rn.read_rows(path)]

        self.assertEqual(stable(run / elf["run_dir"] / "trials.jsonl"), stable(direct / "trials.jsonl"))

    def test_invalid_caps_and_workers_are_refused(self):
        run = _two_cells()
        for kwargs in ({"max_usd": 0}, {"max_usd": -1}, {"max_usd_per_cell": 0}, {"workers": 0}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    base.run_baselines(run, [f"{OPUS}/{ELF}"], Priced(), n_trials=1, **kwargs)
        err = io.StringIO()
        with redirect_stderr(err):
            with self.assertRaises(SystemExit):
                base.main(["--run", str(run), "--cells", str(run / "cells.txt"), "--fixture", str(run / "nope.json"),
                           "--max-usd", "0"])
            with self.assertRaises(SystemExit):
                base.main(["--run", str(run), "--cells", str(run / "cells.txt"), "--fixture", str(run / "nope.json"),
                           "--max-usd-per-cell", "-1"])
            with self.assertRaises(SystemExit):
                idn.main(["--run", str(run), "--fixture", str(run / "nope.json"), "--workers", "0"])
        self.assertIn("must be > 0", err.getvalue())
        self.assertIn("must be an int >= 1", err.getvalue())

    def test_selection_stopped_at_12_of_30_does_not_call_decide(self):
        run = _ideation_run()
        proposal = _proposal()
        (run / "ideation.jsonl").write_text(json.dumps(proposal) + "\n", encoding="utf-8")
        stub = Priced(cost=1.0)
        with mock_patch.object(idn, "decide", wraps=idn.decide) as decide:
            row = idn.evaluate(run, proposal, stub, n_trials=30, spend_cap_usd=12.0)
        decide.assert_not_called()
        self.assertIsNone(row["candidate"])
        self.assertIsNot(row["candidate"], False)
        self.assertTrue(row["stopped_by_cap"])
        self.assertEqual(row["trials_completed"], 12)
        self.assertEqual(row["stop_reason"], "max_usd_per_cell")
        self.assertEqual(len(stub.calls), 12)
        self.assertEqual(len(rn.read_rows(run / row["selection_run_dir"] / "trials.jsonl")), 12)
        self.assertIsNone(row["alpha"])
        self.assertIsNone(row["success"])

    def test_confirmation_stopped_partway_stays_unconfirmed(self):
        run = _ideation_run()
        _install_baseline(run, completed=2)
        proposal = _proposal()
        # n=2, $1 each. Selection uses $2 and completes (2 passes > baseline 0). Cap $3
        # allows one confirmation trial, then stops. decide runs for selection only.
        stub = Priced(passes=_passes(ELF, 2), cost=1.0)
        with mock_patch.object(idn, "decide", wraps=idn.decide) as decide:
            row = idn.evaluate(run, proposal, stub, n_trials=2, spend_cap_usd=3.0)
        self.assertEqual(decide.call_count, 1)
        self.assertTrue(row["candidate"])
        self.assertIsNone(row["confirmed"])
        self.assertIsNone(row["success"])
        self.assertTrue(row["stopped_by_cap"])
        self.assertEqual(row["trials_completed"], 1)
        self.assertEqual(row["stop_reason"], "max_usd_per_cell")
        self.assertFalse((run / "ideation" / proposal["proposal_id"] / "confirm-baseline").exists())

    def test_per_cell_cap_is_shared_across_proposals_and_confirm_top(self):
        run = _ideation_run()
        _install_baseline(run, completed=2)
        first = _proposal()
        second_patch = {"schema": pt.PATCH_SCHEMA, "ops": [{"op": "system_append", "text": "other"}]}
        second = dict(first, index=1, proposal_id=pt.patch_id(second_patch), patch=second_patch,
                      parent_trial_id="parent-2")
        (run / "ideation.jsonl").write_text("".join(json.dumps(row) + "\n" for row in (first, second)),
                                            encoding="utf-8")
        (run / "credit_draw.json").write_text(json.dumps({
            f"{OPUS}/{ELF}": {"status": "IN", "picks": [
                {"draw_order": 1, "slot": 0, "trial_id": "parent-1"},
                {"draw_order": 2, "slot": 1, "trial_id": "parent-2"},
            ]},
        }), encoding="utf-8")
        # Parent trials so confirm=top can see the draw. The picks only need to be in the file.
        ledger = rn.SpendLedger(max_usd_per_cell=2.0)
        stub = Priced(passes=_passes(ELF, 2), cost=1.0)
        idn.evaluate(run, first, stub, n_trials=2, spend_cap_usd=2.0, confirm="top", ledger=ledger)
        before = len(stub.calls)
        self.assertEqual(before, 2)
        idn.evaluate(run, second, stub, n_trials=2, spend_cap_usd=2.0, confirm="top", ledger=ledger)
        self.assertEqual(len(stub.calls), before)  # the cell is already at the cap; no new trial
        rows = rn.read_rows(run / "ideation_results.jsonl")
        stopped = [row for row in rows if row.get("stopped_by_cap")]
        self.assertTrue(stopped)
        self.assertTrue(all(row["stop_reason"] == "max_usd_per_cell" for row in stopped))

    def test_cli_cap_stop_exits_zero(self):
        run = _ideation_run()
        proposal = _proposal()
        (run / "ideation.jsonl").write_text(json.dumps(proposal) + "\n", encoding="utf-8")
        fixture = run / "passes.json"
        fixture.write_text(json.dumps({f"{ELF}|{OPUS}": 30}), encoding="utf-8")
        buf = io.StringIO()
        with redirect_stdout(buf), mock_patch.object(idn, "decide", wraps=idn.decide) as decide:
            code = idn.main(["--run", str(run), "--fixture", str(fixture), "--n-trials", "30",
                             "--max-usd-per-cell", "0.12"])
        decide.assert_not_called()
        self.assertEqual(code, 0)
        summary = json.loads(buf.getvalue())
        self.assertEqual(summary["stop_reason"], "max_usd_per_cell")
        self.assertEqual(summary["max_usd_per_cell"], 0.12)
        self.assertIsNone(summary["max_usd"])
        row = rn.read_rows(run / "ideation_results.jsonl")[0]
        self.assertEqual(row["trials_completed"], 12)
        self.assertIsNone(row["candidate"])

    def test_a_restart_spends_only_the_remaining_per_cell_budget(self):
        # First process spends 8 of a 10 cap and exits. The next process is a new ledger.
        run = _ideation_run()
        proposal = _proposal()
        (run / "ideation.jsonl").write_text(json.dumps(proposal) + "\n", encoding="utf-8")
        first = Priced(cost=1.0)
        with mock_patch.object(idn, "decide", wraps=idn.decide) as decide:
            stopped = idn.evaluate(run, proposal, first, n_trials=30, spend_cap_usd=8.0)
        decide.assert_not_called()
        self.assertEqual(stopped["trials_completed"], 8)
        self.assertEqual(len(first.calls), 8)
        again = Priced(cost=1.0)
        with mock_patch.object(idn, "decide", wraps=idn.decide) as decide:
            resumed = idn.evaluate(run, proposal, again, n_trials=30, spend_cap_usd=10.0)
        decide.assert_not_called()
        self.assertTrue(resumed["stopped_by_cap"])
        self.assertEqual(resumed["stop_reason"], "max_usd_per_cell")
        self.assertIsNone(resumed["candidate"])
        self.assertEqual(len(again.calls), 2)
        rows = rn.read_rows(run / resumed["selection_run_dir"] / "trials.jsonl")
        self.assertEqual(len(rows), 10)
        self.assertEqual(sum(row["cost_usd"] for row in rows), 10.0)
        self.assertEqual(len({row["trial_id"] for row in rows}), 10)

    def test_baseline_spend_counts_toward_a_later_max_usd(self):
        run = _two_cells()
        base.run_baselines(run, [f"{OPUS}/{ELF}"], Priced(cost=1.0), n_trials=4)
        proposal = _proposal()
        (run / "ideation.jsonl").write_text(json.dumps(proposal) + "\n", encoding="utf-8")
        stub = Priced(cost=1.0)
        with mock_patch.object(idn, "decide", wraps=idn.decide) as decide:
            row = idn.evaluate(run, proposal, stub, n_trials=30, max_usd=6.0)
        decide.assert_not_called()
        self.assertEqual(len(stub.calls), 2)
        self.assertTrue(row["stopped_by_cap"])
        self.assertEqual(row["stop_reason"], "max_usd")
        self.assertIsNone(row["candidate"])
        self.assertEqual(row["trials_completed"], 2)

    def test_a_trial_id_already_on_disk_is_counted_once(self):
        run = _ideation_run()
        pilot = sum(row.get("cost_usd") or 0.0 for row in rn.read_rows(run / "trials.jsonl"))
        self.assertGreater(pilot, 0.0)
        row = {"trial_id": "t-once", "model": OPUS, "task": ELF, "cost_usd": 4.0}
        for label in ("select", "confirm"):
            path = run / "ideation" / "pid" / label / "trials.jsonl"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
        ledger = rn.SpendLedger(max_usd=10.0, max_usd_per_cell=10.0)
        ledger.seed_run(run)
        ledger.seed_run(run)
        ledger.note_rows([dict(row)])
        self.assertEqual(ledger.spent_total(), 4.0)
        self.assertEqual(ledger.spent_cell(OPUS, ELF), 4.0)
        self.assertNotIn("t-once", ledger.missing(["t-once"]))


class WorkersAndLock(unittest.TestCase):
    def setUp(self):
        patcher = mock_patch.dict(os.environ, {hs_config.CUTOFF_ENV: ""})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_workers_run_concurrently_and_are_recorded(self):
        run = _two_cells()
        barrier = threading.Barrier(4)
        entered = threading.Event()

        class Concurrent(Priced):
            def run_trial(self, spec, run_dir):
                with self._lock:
                    self.calls.append(spec)
                    self.inflight += 1
                    self.peak = max(self.peak, self.inflight)
                    self.active_runs.add(spec.run_id)
                    self.peak_runs = max(self.peak_runs, len(self.active_runs))
                    if self.inflight == 4:
                        entered.set()
                barrier.wait(5)
                with self._lock:
                    self.inflight -= 1
                    if self.inflight == 0:
                        self.active_runs.clear()
                        entered.clear()
                trace = f"{spec.trial_dir}/trace.jsonl"
                path = Path(run_dir) / trace
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('{"step": 1}\n', encoding="utf-8")
                return rn.TrialResult(status="completed", passed=False, checker_exit=1, steps=1,
                                      cost_usd=self.cost, trace=trace)

        stub = Concurrent(cost=0.01)
        manifests = base.run_baselines(run, [f"{OPUS}/{ELF}", f"{OPUS}/{QUERY}"], stub, n_trials=4, workers=4)
        self.assertEqual(len(stub.calls), 8)
        self.assertEqual(stub.peak, 4)
        self.assertEqual(stub.peak_runs, 1)  # one arm at a time, even with 4 workers
        for row in manifests.values():
            self.assertEqual(row["workers"], 4)
            trials = rn.read_rows(run / row["run_dir"] / "trials.jsonl")
            self.assertEqual(sorted(trial["trial_index"] for trial in trials), [0, 1, 2, 3])
            self.assertTrue(all(trial["workers"] == 4 for trial in trials))
            self.assertTrue(all(set(trial["host_load"]) == {"start", "end", "cpus"} for trial in trials))
            plan = json.loads((run / row["run_dir"] / "plan.json").read_text(encoding="utf-8"))
            self.assertEqual(plan["workers"], 4)
            self.assertEqual(plan["config"]["workers"], 4)
            self.assertTrue(plan["arm_lock"]["acquired"])
            self.assertIn("arm.lock", plan["arm_lock"]["path"])

    def test_cap_reserves_in_flight_trials(self):
        run = _two_cells()
        hold = threading.Event()
        ready = threading.Event()
        stub = Priced(cost=1.0, hold=hold, ready=ready, ready_at=3)
        box = {}

        def go():
            try:
                box["manifests"] = base.run_baselines(
                    run, [f"{OPUS}/{ELF}"], stub, n_trials=8, workers=8, max_usd_per_cell=3.0)
            except Exception as exc:
                box["error"] = exc

        thread = threading.Thread(target=go)
        thread.start()
        self.assertTrue(ready.wait(5), "three trials did not start")
        self.assertEqual(len(stub.calls), 3)
        hold.set()
        thread.join(5)
        self.assertNotIn("error", box)
        self.assertFalse(thread.is_alive())
        rows = rn.read_rows(run / box["manifests"][f"{OPUS}/{ELF}"]["run_dir"] / "trials.jsonl")
        self.assertEqual(len(rows), 3)
        self.assertLessEqual(sum(row["cost_usd"] for row in rows), 3.0)
        self.assertTrue(all(row["workers"] == 8 for row in rows))

    def test_a_second_arm_refuses_while_the_lock_is_held(self):
        run = _ideation_run()
        _install_baseline(run)
        proposal = _proposal()
        base_cfg = json.loads((run / "plan.json").read_text(encoding="utf-8"))["config"]
        recorded = {"ref": "recorded:test", "id": "sha256:" + "11" * 32, "matches_pin": True}
        started = threading.Event()
        release = threading.Event()

        class Blocking(Priced):
            def run_trial(self, spec, run_dir):
                started.set()
                release.wait(5)
                return super().run_trial(spec, run_dir)

        first = Blocking(cost=0.01)
        box = {}

        def go():
            try:
                box["row"] = idn._arm(run, base_cfg, proposal, "select", True, first, 1, None, recorded)
            except Exception as exc:
                box["error"] = exc

        thread = threading.Thread(target=go)
        thread.start()
        self.assertTrue(started.wait(5))
        other = Priced(cost=0.01)
        with self.assertRaises(rn.ArmBusy):
            idn._arm(run, base_cfg, proposal, "confirm", True, other, 1, None, recorded)
        self.assertEqual(other.calls, [])
        release.set()
        thread.join(5)
        self.assertNotIn("error", box)

    def test_a_lock_held_outside_the_process_is_refused(self):
        run = _ideation_run()
        proposal = _proposal()
        base_cfg = json.loads((run / "plan.json").read_text(encoding="utf-8"))["config"]
        recorded = {"ref": "recorded:test", "id": "sha256:" + "11" * 32, "matches_pin": True}
        handle = rn.ARM_LOCK_PATH.open("a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            stub = Priced(cost=0.01)
            with self.assertRaises(rn.ArmBusy) as caught:
                idn._arm(run, base_cfg, proposal, "select", True, stub, 1, None, recorded)
            self.assertIn("refusing to start a second arm", str(caught.exception))
            self.assertEqual(stub.calls, [])
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    def test_worker_mismatch_is_refused_and_a_missing_field_warns(self):
        run = _ideation_run()
        proposal = _proposal()
        _install_baseline(run, workers=1, completed=1)
        stub = Priced(cost=0.01)
        with self.assertRaisesRegex(ValueError, "workers=4"):
            idn.evaluate(run, proposal, stub, n_trials=1, workers=4)
        self.assertEqual(stub.calls, [])
        doc = json.loads((run / "credit_baseline.json").read_text(encoding="utf-8"))
        del doc[f"{OPUS}/{ELF}"]["workers"]
        (run / "credit_baseline.json").write_text(json.dumps(doc) + "\n", encoding="utf-8")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            idn.evaluate(run, proposal, stub, n_trials=1, workers=4)
        self.assertTrue(any("predates" in str(item.message) for item in caught))
        self.assertEqual(len(stub.calls), 1)

    def test_host_load_and_workers_are_on_selection_and_confirmation_rows(self):
        run = _ideation_run()
        _install_baseline(run, completed=1)
        proposal = _proposal()
        stub = Priced(passes=_passes(ELF, 1), cost=0.01)
        row = idn.evaluate(run, proposal, stub, n_trials=1, workers=1)
        self.assertTrue(row["candidate"])
        for rel in (row["selection_run_dir"], *row["confirmation_run_dirs"]):
            trials = rn.read_rows(run / rel / "trials.jsonl")
            self.assertTrue(trials, rel)
            for trial in trials:
                self.assertEqual(trial["workers"], 1)
                self.assertEqual(set(trial["host_load"]), {"start", "end", "cpus"})
                self.assertIsNone(trial["runtime_measured_s"])
                self.assertIsNone(trial["runtime_golden_s"])
                self.assertIsNone(trial["runtime_ratio"])


class Runtime(unittest.TestCase):
    def test_query_optimize_checker_output_parses_the_ratio(self):
        text = (
            "Running iteration 0 of 4\n"
            "{'iterations': 4, 'golden': {'median_s': 0.736, 'min_s': 0.70, 'max_s': 0.80}, "
            "'solution': {'median_s': 0.830, 'min_s': 0.80, 'max_s': 0.90}, "
            "'speedup_solution_vs_golden': 0.8867469879518072}\n"
        )
        parsed = ce.parse_checker_runtime(text)
        self.assertEqual(parsed["runtime_golden_s"], 0.736)
        self.assertEqual(parsed["runtime_measured_s"], 0.830)
        self.assertAlmostEqual(parsed["runtime_ratio"], 0.830 / 0.736, places=3)
        self.assertAlmostEqual(parsed["runtime_ratio"], 1.128, places=3)
        self.assertEqual(ce.parse_checker_runtime("1 failed, 5 passed in 11.16s"),
                         {"runtime_measured_s": None, "runtime_golden_s": None, "runtime_ratio": None})

    def test_parsed_runtime_is_stored_on_the_trial_row(self):
        parsed = ce.parse_checker_runtime(
            "{'golden': {'median_s': 0.736}, 'solution': {'median_s': 0.830}}")

        class Reports(rn.FixtureExecutor):
            def run_trial(self, spec, run_dir):
                result = super().run_trial(spec, run_dir)
                result.runtime_measured_s = parsed["runtime_measured_s"]
                result.runtime_golden_s = parsed["runtime_golden_s"]
                result.runtime_ratio = parsed["runtime_ratio"]
                return result

        directory = Path(os.environ.get("TMPDIR", "/tmp")) / "obench-runtime-row"
        import tempfile
        directory = Path(tempfile.mkdtemp())
        cfg = rn.RunConfig.from_dict({
            "run_id": "runtime", "suite": "pilot", "models": [OPUS], "n_trials": 1,
            "tasks": [ELF], "max_rounds": 1, "fixed_tasks": True,
        })
        rn.Runner(cfg, directory, Reports({})).run()
        row = rn.read_rows(directory / "trials.jsonl")[0]
        self.assertEqual(row["runtime_golden_s"], 0.736)
        self.assertEqual(row["runtime_measured_s"], 0.830)
        self.assertAlmostEqual(row["runtime_ratio"], 1.128, places=3)


if __name__ == "__main__":
    unittest.main()
