"""--cells: run only listed cells, keep trial ids, seeded order and cell keys."""
import json
import tempfile
import unittest
from pathlib import Path

from thesis.ab.compat import Assessment
from thesis.ab.durable import publish_text
from thesis.ab.run_ab import RunError, _cell_rel, cell_file, drive, parse_cells
from obench.tests.test_ab import SHA_A, SHA_B, _csv
from thesis.ab.prs import parse_prs

TASKS = ("model-extraction-relu-logits", "torch-tensor-parallelism")


class CellsTests(unittest.TestCase):
    def _prs(self):
        path = _csv(
            [{"PR": "13090", "Title": "t", "Category": "tool", "Harness change": "x",
              "Merge commit SHA": SHA_B, "Parent/base SHA": SHA_A}],
            ["PR", "Title", "Category", "Harness change", "Merge commit SHA", "Parent/base SHA"],
        )
        self.addCleanup(path.unlink)
        return parse_prs(path)

    def _run(self, trials, cells=None, order="interleave", seed=7):
        out = Path(tempfile.mkdtemp())
        calls = []

        def worker(spec):
            calls.append((spec["side"], spec["task"], spec["trial"], spec["cell_path"]))
            publish_text(Path(spec["cell_path"]), json.dumps({
                "task": spec["task"], "trial": spec["trial"], "score": 1,
                "tokens_input_uncached": 10, "tokens_output": 10,
                "tokens_cache_read": 0, "tokens_cache_write": 0,
            }))

        _p, launched, stopped = drive(
            self._prs(), TASKS, trials, out, jobs=1, model="claude-opus-5-5",
            timeout_s=5, cache=out, max_cost_usd=None, dry_run=False,
            tasks_dir=Path("/tmp"), build_fn=lambda sha, cache, repo="": Path("/tmp") / sha,
            assess_fn=lambda b: Assessment("native", "listed", {}, False),
            worker=worker, order=order, seed=seed, cells=cells,
        )
        self.assertIsNone(stopped)
        return out, calls

    def test_runs_only_listed_cells_with_original_trials_and_paths(self):
        prs = self._prs()
        keys = parse_cells(
            "with/model-extraction-relu-logits/3,with/model-extraction-relu-logits/7,"
            "without/model-extraction-relu-logits/10", prs)
        out, calls = self._run(10, keys)
        got = {(s, t, n) for s, t, n, _ in calls}
        self.assertEqual(got, {("with", TASKS[0], 3), ("with", TASKS[0], 7), ("without", TASKS[0], 10)})
        for side, task, trial, path in calls:
            self.assertEqual(Path(path), cell_file(out, "13090", side, task, trial))
            self.assertEqual(json.loads(Path(path).read_text())["trial"], trial)

    def test_order_is_subsequence_of_full_seeded_plan(self):
        _o, full = self._run(10)
        keys = parse_cells("13090/with/torch-tensor-parallelism/2,with/model-extraction-relu-logits/7,"
                           "without/model-extraction-relu-logits/4", self._prs())
        _o, sub = self._run(10, keys)
        full_ids = [c[:3] for c in full]
        sub_ids = [c[:3] for c in sub]
        self.assertEqual(sub_ids, [c for c in full_ids if c in set(sub_ids)])

    def test_trial_above_trials_still_planned_at_its_id(self):
        keys = parse_cells("without/model-extraction-relu-logits/10", self._prs())
        _o, calls = self._run(1, keys)
        self.assertEqual([c[:3] for c in calls], [("without", TASKS[0], 10)])

    def test_absent_option_is_full_plan(self):
        _o, calls = self._run(2)
        self.assertEqual(len(calls), 2 * 2 * 2)

    def test_file_forms(self):
        prs = self._prs()
        d = Path(tempfile.mkdtemp())
        lines = d / "cells.txt"
        lines.write_text("# reruns\nwith/model-extraction-relu-logits/3\n\n13090/with/model-extraction-relu-logits/7\n")
        js = d / "cells.json"
        js.write_text(json.dumps({"rerun": ["13090/cells/with/model-extraction-relu-logits/3.json",
                                            "with/model-extraction-relu-logits/7"]}))
        want = {_cell_rel(dict(pr="13090", side="with", task=TASKS[0], trial=n)) for n in (3, 7)}
        self.assertEqual(parse_cells(str(lines), prs), want)
        self.assertEqual(parse_cells(str(js), prs), want)

    def test_existing_target_cell_refuses_and_runs_nothing(self):
        out = Path(tempfile.mkdtemp())
        existing = cell_file(out, "13090", "with", TASKS[0], 3)
        publish_text(existing, json.dumps({"task": TASKS[0], "trial": 3, "score": 1}))
        before = existing.read_bytes()
        calls = []
        keys = parse_cells(f"with/{TASKS[0]}/3,with/{TASKS[0]}/7", self._prs())
        with self.assertRaises(RunError) as raised:
            drive(
                self._prs(), TASKS, 10, out, jobs=1, model="claude-opus-5-5",
                timeout_s=5, cache=out, max_cost_usd=None, dry_run=False,
                tasks_dir=Path("/tmp"),
                build_fn=lambda sha, cache, repo="": calls.append("build") or Path("/tmp") / sha,
                assess_fn=lambda b: Assessment("native", "listed", {}, False),
                worker=lambda spec: calls.append(spec["trial"]), cells=keys,
            )
        self.assertIn("13090/cells/with/model-extraction-relu-logits/3.json", str(raised.exception))
        self.assertNotIn("/7.json", str(raised.exception))
        self.assertEqual(calls, [])
        self.assertEqual(existing.read_bytes(), before)
        self.assertFalse(cell_file(out, "13090", "with", TASKS[0], 7).exists())

    def test_invalid_entries_rejected(self):
        prs = self._prs()
        for bad in ("with/x", "with/model-extraction-relu-logits/0", "with/t/abc", ""):
            with self.assertRaises(RunError):
                parse_cells(bad, prs)
        for bad in ("sideways/model-extraction-relu-logits/1", "with/not-a-task/1", "999/with/model-extraction-relu-logits/1"):
            with self.assertRaises(RunError):
                self._run(2, parse_cells(bad, prs))


if __name__ == "__main__":
    unittest.main()
