"""SEA-106: OpenBench Hard suite lists, loading by id, and the per-model
harder-swap rule (obench/hardsuite). No trials are run."""

from __future__ import annotations

import csv
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from obench.hardsuite import config, swap
from obench.hardsuite.suite import (REPO_ROOT, SOURCES, SuiteError, load_suite, load_task, resolve)

RATES = REPO_ROOT / "data/packs/openbench-tb-hard/tb2-frontier-rates.csv"


class PilotSuite(unittest.TestCase):
    def setUp(self):
        self.pilot, self.pool = load_suite("pilot"), load_suite("pilot-pool")

    def test_ten_tasks_justified_and_loadable_by_id(self):
        self.assertEqual(len(self.pilot.tasks), 10)
        self.assertEqual(self.pilot.planned_size, 10)
        for task in self.pilot.tasks:
            tasks_dir, task_id = load_task("pilot", task.id)
            self.assertEqual(task_id, task.id)
            self.assertTrue((Path(tasks_dir) / task_id / "instruction.md").is_file())
            self.assertGreater(len(task.why), 40)
        self.assertEqual(len({t.domain for t in self.pilot.tasks}), 10)  # one per domain

    def test_pilot_is_neither_trivial_nor_impossible(self):
        rates = [t.frontier_rate for t in self.pilot.tasks]
        self.assertGreater(min(rates), 0.0)
        self.assertLess(max(rates), 0.85)

    def test_rates_match_the_published_rates_csv(self):
        with RATES.open() as fh:
            published = {r["task"]: float(r["rate"]) for r in csv.DictReader(fh)}
        for task in (*self.pilot.tasks, *self.pool.tasks):
            self.assertAlmostEqual(task.frontier_rate, round(published[task.id], 3), places=3, msg=task.id)

    def test_pool_is_harder_disjoint_and_loadable(self):
        self.assertFalse(set(self.pilot.ids()) & set(self.pool.ids()))
        easiest_pilot = max(t.frontier_rate for t in self.pilot.tasks)
        for task in self.pool.tasks:
            resolve(task)
            self.assertLess(task.frontier_rate, easiest_pilot)
        self.assertTrue(all(c["harder_in_pool"] >= 5 for c in swap.pool_capacity(self.pilot, self.pool)))

    def test_every_source_records_its_bench_snapshot(self):
        for name, source in SOURCES.items():
            self.assertRegex(source["commit"], r"^[0-9a-f]{40}$", name)
            self.assertTrue((REPO_ROOT / source["tasks_dir"]).is_dir(), name)
        self.assertEqual(self.pilot.tasks[0].bench["commit"], "2fd12b88aafdd04a52c298e3940bcb189f9766d6")


class Cutoff(unittest.TestCase):
    def test_single_default_constant(self):
        self.assertEqual(config.PASS_CUTOFF, 0.90)
        with patch.dict(os.environ, {config.CUTOFF_ENV: ""}):
            self.assertEqual(config.pass_cutoff(), 0.90)
        with patch.dict(os.environ, {config.CUTOFF_ENV: "0.95"}):
            self.assertEqual(config.pass_cutoff(), 0.95)
        with patch.dict(os.environ, {config.CUTOFF_ENV: "1.5"}), self.assertRaises(ValueError):
            config.pass_cutoff()

    def test_cutoff_is_not_hard_coded_elsewhere(self):
        pkg = Path(config.__file__).parent
        for path in pkg.rglob("*.py"):
            if path.name == "config.py":
                continue
            self.assertNotRegex(path.read_text(), r"0\.9[05]?\b", path.name)

    def test_passed_is_exact_at_the_boundary(self):
        self.assertTrue(swap.passed(27, 30, 0.90))
        self.assertFalse(swap.passed(26, 30, 0.90))
        self.assertTrue(swap.passed(29, 30, 0.95))  # 28.5 rounds up
        self.assertFalse(swap.passed(28, 30, 0.95))
        with patch.dict(os.environ, {config.CUTOFF_ENV: ""}):
            self.assertTrue(swap.passed(9, 10))
        for bad in ((5, 0), (31, 30), (-1, 30), (True, 30)):
            with self.subTest(bad=bad), self.assertRaises(swap.SwapError):
                swap.passed(*bad, 0.9)


class SwapRule(unittest.TestCase):
    def setUp(self):
        self.pilot, self.pool = load_suite("pilot"), load_suite("pilot-pool")
        self.patch = patch.dict(os.environ, {config.CUTOFF_ENV: ""})
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_pass_swaps_for_that_model_only_and_keeps_size(self):
        opus = swap.initial_state("claude-opus", self.pilot)
        carbon = swap.initial_state("gemini-4-carbon", self.pilot)
        opus2, swaps = swap.apply_results(opus, {"sanitize-git-repo": (28, 30), "extract-elf": (20, 30)},
                                          self.pilot, self.pool)
        self.assertEqual(swaps, [{"slot": 9, "from": "sanitize-git-repo", "to": "polyglot-c-py",
                                  "from_rate": 0.692, "to_rate": 0.385, "successes": 28, "trials": 30,
                                  "cutoff": 0.9}])
        self.assertEqual(len(swap.current_tasks(opus2)), 10)
        self.assertIn("extract-elf", swap.current_tasks(opus2))  # 20/30 < 90%: kept
        self.assertEqual(swap.current_tasks(carbon), self.pilot.ids())  # other model untouched
        self.assertEqual(swap.current_tasks(opus), self.pilot.ids())  # input state not mutated
        self.assertEqual(opus2["slots"][9]["retired"], ["sanitize-git-repo"])

    def test_replacement_is_strictly_harder_and_climbs_one_rung(self):
        state = swap.initial_state("m", self.pilot)
        state, swaps = swap.apply_results(state, {"model-extraction-relu-logits": (30, 30)}, self.pilot, self.pool)
        self.assertEqual(swaps[0]["to"], "video-processing")  # easiest pool task below 0.25
        state, swaps = swap.apply_results(state, {"video-processing": (30, 30)}, self.pilot, self.pool)
        self.assertEqual(swaps[0]["to"], "filter-js-from-html")  # next rung (0.0), lowest id among ties
        self.assertEqual(state["slots"][1]["retired"], ["model-extraction-relu-logits", "video-processing"])
        self.assertEqual(len(state["swaps"]), 2)

    def test_equal_rate_is_not_harder(self):
        state = swap.initial_state("m", self.pilot)
        state, swaps = swap.apply_results(state, {"polyglot-rust-c": (30, 30)}, self.pilot, self.pool)
        self.assertNotEqual(swaps[0]["to"], "polyglot-c-py")  # same 0.385 rate
        self.assertLess(swaps[0]["to_rate"], 0.385)

    def test_no_task_is_reused_within_a_model(self):
        state = swap.initial_state("m", self.pilot)
        everything = {t: (30, 30) for t in self.pilot.ids()[3:]}  # 7 passes, pool has 7 tasks
        state, swaps = swap.apply_results(state, everything, self.pilot, self.pool)
        self.assertEqual(len(swaps), 7)
        tasks = swap.current_tasks(state)
        self.assertEqual(len(tasks), len(set(tasks)))

    def test_exhausted_pool_fails_without_shrinking(self):
        state = swap.initial_state("m", self.pilot)
        everything = {t: (30, 30) for t in self.pilot.ids()}
        with self.assertRaises(swap.PoolExhausted):
            swap.apply_results(state, everything, self.pilot, self.pool)
        self.assertEqual(swap.current_tasks(state), self.pilot.ids())

    def test_results_must_name_current_tasks(self):
        state = swap.initial_state("m", self.pilot)
        with self.assertRaises(swap.SwapError):
            swap.apply_results(state, {"regex-chess": (30, 30)}, self.pilot, self.pool)


class SuiteFiles(unittest.TestCase):
    def write(self, d, body):
        Path(d, "s.toml").write_text('schema = "openbench.hard-suite/v1"\nname = "s"\n' + body)
        return load_suite("s", Path(d))

    def test_bad_suites_are_refused(self):
        task = '[[task]]\nid = "dna-insert"\nsource = "{src}"\nfrontier_rate = {rate}\ndomain = "x"\nwhy = "{why}"\n'
        with tempfile.TemporaryDirectory() as d:
            for src, rate, why, msg in (("nope", 0.1, "w", "unknown source"), ("openbench-tb-hard", 1.5, "w", "not in"),
                                        ("openbench-tb-hard", 0.1, " ", "no rationale")):
                with self.subTest(msg=msg), self.assertRaisesRegex(SuiteError, msg):
                    self.write(d, task.format(src=src, rate=rate, why=why))
            with self.assertRaisesRegex(SuiteError, "duplicate"):
                self.write(d, task.format(src="openbench-tb-hard", rate=0.1, why="w") * 2)
            missing = self.write(d, task.format(src="openbench-tb-hard", rate=0.1, why="w").replace(
                "dna-insert", "no-such-task"))
            with self.assertRaisesRegex(SuiteError, "missing"):
                resolve(missing.tasks[0])
            with self.assertRaises(swap.SwapError):
                swap.initial_state("m", self.write(d, "planned_size = 3\n" + task.format(
                    src="openbench-tb-hard", rate=0.1, why="w")))

    def test_readme_explains_add_and_swap(self):
        readme = Path(config.__file__).with_name("README.md").read_text()
        for heading in ("## Add a task", "## Swap tasks by hand", "## Pass cutoff and the swap rule"):
            self.assertIn(heading, readme)
        self.assertTrue(re.search(r"PASS_CUTOFF = 0\.90", readme))


if __name__ == "__main__":
    unittest.main()
