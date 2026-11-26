"""Fresh baseline: recorded image, knob off, and the manifest evaluate reads. Offline stubs only."""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch as mock_patch

from obench.reflection import credit_baseline as base
from obench.reflection import runner as rn
from obench.reflection import vertex_models as vm

OPUS = "claude-opus-5-5"
ELF = "extract-elf"
QUERY = "query-optimize"
ELF_IMAGE = {"ref": "openbench-tb2-extract-elf:pinned", "id": "sha256:" + "a1" * 32, "matches_pin": True}
QUERY_IMAGE = {"ref": "openbench-tb2-query-optimize:pinned", "id": "sha256:" + "b2" * 32, "matches_pin": False}


class Stub:
    """Trial outcomes by (task, model). Records the spec and whether the knob was off."""

    def __init__(self, passes, blocked=None, cost=0.25):
        self.passes, self.blocked, self.cost = passes, blocked or {}, cost
        self.calls, self.seen_smoke = [], []
        self.smoke_compaction = True

    def estimate_cost_usd(self, model):
        return self.cost

    def run_trial(self, spec, run_dir):
        self.calls.append(spec)
        self.seen_smoke.append(self.smoke_compaction)
        trace = f"{spec.trial_dir}/trace.jsonl"
        path = Path(run_dir) / trace
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"step": 1}\n', encoding="utf-8")
        key = (spec.task, spec.model)
        if spec.trial_index < self.blocked.get(key, 0):
            return rn.TrialResult(status="provider_blocked", passed=None, cost_usd=self.cost,
                                  provider_blocked={"blockReason": "SAFETY"}, trace=trace)
        passed = spec.trial_index < self.blocked.get(key, 0) + self.passes.get(key, 0)
        return rn.TrialResult(status="completed", passed=passed, checker_exit=0 if passed else 1,
                              steps=1, cost_usd=self.cost, trace=trace)


def _parent(tasks=("extract-elf", "query-optimize")):
    run = Path(tempfile.mkdtemp())
    cfg = rn.RunConfig.from_dict({
        "run_id": "pilot", "suite": "pilot", "models": [OPUS], "n_trials": 1,
        "tasks": list(tasks), "max_rounds": 1, "fixed_tasks": True,
    })
    rn.Runner(cfg, run, rn.FixtureExecutor({(task, OPUS): 0 for task in tasks})).run()
    return run


def _stamp(run: Path, images: dict):
    rows = []
    for row in rn.read_rows(run / "trials.jsonl"):
        image = images.get(row["task"])
        if image:
            row.update(image_ref=image["ref"], image_id=image["id"], image_matches_pin=image["matches_pin"],
                       code_commit="422e818a")
        rows.append(row)
    (run / "trials.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _blocked(run: Path, task: str, n: int):
    rows = [json.dumps({
        "run_id": "pilot", "trial_id": f"aside-{task}-{i}", "task": task, "model": OPUS, "patch_id": None,
        "trial_index": 10 + i, "status": "provider_blocked", "passed": None,
    }) for i in range(n)]
    with (run / "trials.jsonl").open("a", encoding="utf-8") as fh:
        fh.write("\n".join(rows) + "\n")


class FreshBaseline(unittest.TestCase):
    def test_recorded_image_knob_off_and_the_manifest(self):
        run = _parent()
        _stamp(run, {ELF: ELF_IMAGE, QUERY: QUERY_IMAGE})
        _blocked(run, "dna-insert", 4)
        before = (run / "trials.jsonl").read_text(encoding="utf-8")
        stub = Stub(passes={(ELF, OPUS): 10, (QUERY, OPUS): 4}, blocked={(QUERY, OPUS): 1})
        cells = [f"{OPUS}/{ELF}", f"{OPUS}/{QUERY}", f"{OPUS}/dna-insert", f"{OPUS}/query-optimise"]
        with mock_patch.dict(os.environ, {vm.SMOKE_COMPACTION_ENV: "1"}):
            manifests = base.run_baselines(run, cells, stub)
        self.assertTrue(stub.smoke_compaction)  # restored after the run
        self.assertTrue(stub.seen_smoke)
        self.assertTrue(all(flag is False for flag in stub.seen_smoke))
        self.assertEqual(len(stub.calls), 60)  # 30 per admitted cell; default N
        self.assertEqual({spec.task for spec in stub.calls}, {ELF, QUERY})
        self.assertTrue(all(spec.patch is None and spec.patch_id is None for spec in stub.calls))
        self.assertEqual((run / "trials.jsonl").read_text(encoding="utf-8"), before)

        self.assertEqual(set(manifests), {f"{OPUS}/{ELF}", f"{OPUS}/{QUERY}"})
        elf, query = manifests[f"{OPUS}/{ELF}"], manifests[f"{OPUS}/{QUERY}"]
        commit = rn.code_commit()["commit"]
        self.assertEqual(elf["baseline_commit"], commit)
        self.assertEqual(elf["code_commit"], commit)
        self.assertEqual(query["baseline_commit"], commit)
        self.assertEqual(query["code_commit"], commit)
        self.assertNotEqual(commit, "422e818a")
        self.assertEqual(elf["passes"], 10)
        self.assertEqual(elf["completed"], 30)
        self.assertEqual(elf["set_aside"], 0)
        self.assertEqual(elf["cost_usd"], 7.5)
        self.assertFalse(elf["smoke_compaction"])
        self.assertFalse(elf["smoke_compaction_profile"]["enabled"])
        self.assertEqual(elf["smoke_compaction_profile"]["context_limit"], vm.DEFAULT_CONTEXT_LIMIT)
        self.assertEqual(elf["image"], {"ref": ELF_IMAGE["ref"], "id": ELF_IMAGE["id"]})
        self.assertIs(elf["image_matches_pin"], True)
        self.assertIs(elf["image_matches_pin_false"], False)
        self.assertEqual(elf["image_source"], "recorded")

        self.assertEqual(query["passes"], 4)
        self.assertEqual(query["completed"], 29)
        self.assertEqual(query["set_aside"], 1)
        self.assertEqual(query["cost_usd"], 7.5)
        self.assertEqual(query["image"], {"ref": QUERY_IMAGE["ref"], "id": QUERY_IMAGE["id"]})
        self.assertIs(query["image_matches_pin"], False)
        self.assertIs(query["image_matches_pin_false"], True)
        on_disk = json.loads((run / "credit_baseline.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk, manifests)
        filename = f"{OPUS}__{QUERY}.json"
        per_cell = json.loads((run / "credit_baseline" / filename).read_text(encoding="utf-8"))
        self.assertEqual(per_cell, query)
        self.assertIn('"image_matches_pin_false": true',
                      (run / "credit_baseline" / filename).read_text(encoding="utf-8"))

        for spec in stub.calls:
            image = QUERY_IMAGE if spec.task == QUERY else ELF_IMAGE
            self.assertEqual(spec.recorded_image, image)
            self.assertIn("--baseline--", spec.run_id)
        child = run / "credit_baseline" / "runs" / f"{OPUS}__{QUERY}"
        plan = json.loads((child / "plan.json").read_text(encoding="utf-8"))
        self.assertFalse(plan["config"]["smoke_compaction"])
        self.assertFalse(plan["smoke_compaction"]["enabled"])
        self.assertEqual(plan["config"]["recorded_image"], QUERY_IMAGE)
        self.assertEqual(plan["code"]["commit"], commit)

    def test_a_different_fresh_image_is_refused(self):
        run = _parent((ELF,))
        _stamp(run, {ELF: ELF_IMAGE})

        class Repin(Stub):
            def run_trial(self, spec, run_dir):
                result = super().run_trial(spec, run_dir)
                result.image = {"ref": "other:tag", "id": "sha256:" + "ff" * 32, "matches_pin": True}
                return result

        stub = Repin(passes={(ELF, OPUS): 1})
        with self.assertRaisesRegex(base.BaselineError, "recorded image"):
            base.run_baselines(run, [f"{OPUS}/{ELF}"], stub, n_trials=1)
        self.assertFalse((run / "credit_baseline.json").exists())
        self.assertEqual(len(stub.calls), 1)
        self.assertFalse((run / "credit_baseline" / "runs" / f"{OPUS}__{ELF}.incoming").exists())

    def test_a_failed_rerun_keeps_the_published_baseline(self):
        run = _parent((ELF,))
        _stamp(run, {ELF: ELF_IMAGE})
        first = base.run_baselines(run, [f"{OPUS}/{ELF}"], Stub(passes={(ELF, OPUS): 1}), n_trials=2)
        manifest = (run / "credit_baseline.json").read_text(encoding="utf-8")
        trials = (run / first[f"{OPUS}/{ELF}"]["run_dir"] / "trials.jsonl").read_text(encoding="utf-8")
        per_cell = (run / "credit_baseline" / f"{OPUS}__{ELF}.json").read_text(encoding="utf-8")

        class Repin(Stub):
            def run_trial(self, spec, run_dir):
                result = super().run_trial(spec, run_dir)
                result.image = {"ref": "other:tag", "id": "sha256:" + "ff" * 32, "matches_pin": True}
                return result

        with self.assertRaisesRegex(base.BaselineError, "refusing to re-pin"):
            base.run_baselines(run, [f"{OPUS}/{ELF}"], Repin(passes={(ELF, OPUS): 2}), n_trials=2)
        self.assertEqual((run / "credit_baseline.json").read_text(encoding="utf-8"), manifest)
        self.assertEqual((run / "credit_baseline" / f"{OPUS}__{ELF}.json").read_text(encoding="utf-8"), per_cell)
        published = run / first[f"{OPUS}/{ELF}"]["run_dir"] / "trials.jsonl"
        self.assertEqual(published.read_text(encoding="utf-8"), trials)
        self.assertEqual(json.loads(manifest)[f"{OPUS}/{ELF}"]["passes"], 1)
        self.assertFalse((run / "credit_baseline" / "runs" / f"{OPUS}__{ELF}.incoming").exists())

    def test_mixed_or_missing_recorded_images_and_a_patched_cell_do_not_run(self):
        run = _parent((ELF,))
        rows = rn.read_rows(run / "trials.jsonl")
        rows.append(dict(rows[0], trial_id="other", image_ref="other:tag", image_id="sha256:" + "c3" * 32,
                         image_matches_pin=True))
        rows[0].update(image_ref=ELF_IMAGE["ref"], image_id=ELF_IMAGE["id"], image_matches_pin=True)
        (run / "trials.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        stub = Stub(passes={(ELF, OPUS): 1})
        with self.assertRaisesRegex(base.BaselineError, "recorded images"):
            base.run_baselines(run, [f"{OPUS}/{ELF}"], stub, n_trials=1)
        self.assertEqual(stub.calls, [])
        self.assertTrue(stub.smoke_compaction)

        bare = _parent((ELF,))
        stub = Stub(passes={(ELF, OPUS): 1})
        with self.assertRaisesRegex(base.BaselineError, "no recorded image"):
            base.run_baselines(bare, [f"{OPUS}/{ELF}"], stub, n_trials=1)
        self.assertEqual(stub.calls, [])

        patched = _parent((ELF,))
        rows = rn.read_rows(patched / "trials.jsonl")
        for row in rows:
            row.update(patch_id="patch-1", image_ref=ELF_IMAGE["ref"], image_id=ELF_IMAGE["id"],
                       image_matches_pin=False)
        (patched / "trials.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        stub = Stub(passes={(ELF, OPUS): 1})
        with self.assertRaisesRegex(base.BaselineError, "patched"):
            base.run_baselines(patched, [f"{OPUS}/{ELF}@patch-1"], stub, n_trials=1)
        self.assertEqual(stub.calls, [])

    def test_cli_fixture_runs_n_trials_offline(self):
        run = _parent((ELF,))
        _stamp(run, {ELF: ELF_IMAGE})
        cells = run / "cells.txt"
        cells.write_text(f"{OPUS}/{ELF}\n{OPUS}/typo-cell\n", encoding="utf-8")
        fixture = run / "fixture.json"
        fixture.write_text(json.dumps({f"{ELF}|{OPUS}": 1}), encoding="utf-8")
        buf_out = io.StringIO()
        with contextlib.redirect_stdout(buf_out):
            self.assertEqual(base.main(["--run", str(run), "--cells", str(cells), "--fixture", str(fixture),
                                        "--n-trials", "2"]), 0)
        payload = json.loads(buf_out.getvalue())
        self.assertEqual(payload["cells"], 1)
        self.assertEqual(payload["n_trials"], 2)
        row = json.loads((run / "credit_baseline.json").read_text(encoding="utf-8"))[f"{OPUS}/{ELF}"]
        self.assertEqual((row["passes"], row["completed"], row["n_trials"]), (1, 2, 2))
        self.assertIs(row["image_matches_pin"], True)
        self.assertFalse(row["smoke_compaction"])
        self.assertNotIn(f"{OPUS}/typo-cell", json.loads((run / "credit_baseline.json").read_text(encoding="utf-8")))

    def test_recorded_image_without_a_ref_is_rejected(self):
        with self.assertRaisesRegex(rn.RunnerError, "recorded_image"):
            rn.RunConfig.from_dict({"run_id": "x", "suite": "pilot", "models": [OPUS], "recorded_image": {}})


class LiveCli(unittest.TestCase):
    def _argv(self, *extra):
        return ["--run", "run", "--cells", "cells.txt", *extra]

    def test_cli_rejects_neither_and_both_executor_flags(self):
        cases = (
            self._argv(),
            self._argv("--fixture", "passes.json", "--live"),
        )
        for argv in cases:
            with self.subTest(argv=argv):
                err = io.StringIO()
                with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as caught:
                    base.main(argv)
                code = caught.exception.code
                self.assertIsInstance(code, int)
                self.assertNotEqual(code, 0)
                self.assertTrue(err.getvalue().strip())

    def test_cli_live_reaches_run_baselines_with_the_cell_executor(self):
        from obench.reflection import cell_executor as ce

        run = Path(tempfile.mkdtemp())
        cells = run / "cells.txt"
        cells.write_text(f"{OPUS}/{ELF}\n", encoding="utf-8")
        opencode = run / "bin" / "opencode"
        seen = {}

        def fake_run_baselines(run_dir, cell_names, executor, n_trials=rn.N_TRIALS, max_set_aside=3,
                                max_usd=None, max_usd_per_cell=None, workers=1):
            seen["run_dir"] = Path(run_dir)
            seen["cells"] = cell_names
            seen["executor"] = executor
            seen["n_trials"] = n_trials
            seen["max_usd"] = max_usd
            seen["max_usd_per_cell"] = max_usd_per_cell
            seen["workers"] = workers
            return {}

        real = ce.CellExecutor

        class Offline(real):
            """Skip the pin check and any host probe. The dataclass constructor still runs."""

            def __post_init__(self):
                return None

        buf = io.StringIO()
        with mock_patch.object(base, "run_baselines", fake_run_baselines), \
                mock_patch.object(ce, "CellExecutor", Offline), \
                mock_patch("thesis.ab.vertex_anthropic_proxy.AdcToken", return_value=lambda: "tok"), \
                mock_patch.dict(os.environ, {"GOOGLE_CLOUD_PROJECT": "proj", vm.SMOKE_COMPACTION_ENV: "1"}), \
                contextlib.redirect_stdout(buf):
            self.assertEqual(base.main([
                "--run", str(run), "--cells", str(cells), "--live",
                "--opencode", str(opencode), "--n-trials", "4",
            ]), 0)
        self.assertEqual(seen["n_trials"], 4)
        self.assertIsInstance(seen["executor"], real)
        self.assertIs(type(seen["executor"]), Offline)
        self.assertEqual(seen["run_dir"], run)
        self.assertEqual(seen["cells"], [f"{OPUS}/{ELF}"])
        self.assertEqual(seen["executor"].opencode, opencode)
        self.assertEqual(seen["executor"].project, "proj")
        self.assertIs(seen["executor"].smoke_compaction, False)
        self.assertEqual(seen["executor"].default_image, "h1-env:1027-strace")
        self.assertIs(seen["executor"].use_image_tag, False)
        self.assertEqual(seen["executor"].estimates_usd, ce.DEFAULT_ESTIMATES_USD)
        self.assertEqual((seen["workers"], seen["max_usd"], seen["max_usd_per_cell"]), (1, None, None))
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["n_trials"], 4)
        self.assertEqual(payload["cells"], 0)


if __name__ == "__main__":
    unittest.main()
