"""Reference-solution check: same image, network and checker as a trial; its own oracle.jsonl."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from obench.reflection import validate_reference as vr
from obench.reflection.cell_executor import AGENT_NETWORK, OFFLINE_NETWORK, SINKHOLED_HOSTS, CellExecutor

REPO = Path(__file__).resolve().parents[2]


class FindReference(unittest.TestCase):
    def test_hardsuite_layouts(self):
        self.assertEqual(vr.find_reference(REPO / "tasks-imported/terminal-bench-2/extract-elf")["kind"], "solve.sh")
        self.assertEqual(vr.find_reference(REPO / "data/packs/openbench-tb-mid/sanitize-git-repo")["kind"], "no_reference")
        self.assertEqual(vr.find_reference(REPO / "data/packs/openbench-tb-hard/polyglot-rust-c")["kind"], "overlay")
        self.assertEqual(vr.find_reference(REPO / "data/packs/openbench-tb-hard/dna-insert")["kind"], "overlay")


class FakeExecutor:
    def __init__(self):
        self.solves, self.checks, self.networks = [], [], []

    def isolation_preflight(self):
        return {"ok": True}

    def _task(self, spec):
        return {"dir": Path(spec.tasks_dir) / spec.task, "image": "task-img:pinned", "workdir": "/app",
                "image_source": "task.toml", "agent_timeout": 30, "solution_needs_network": False}

    def resolve_image(self, task, name):
        return dict(task, image_pin=None)

    def image_record(self, task):
        return {"ref": task["image"], "id": "sha256:" + "ab" * 32, "pinned": task["image"], "matches_pin": True}

    def agent_network(self, task):
        self.networks.append("offline")
        return "offline"

    def seed_workspace(self, task, workspace):
        workspace.mkdir(parents=True, exist_ok=True)
        return {"files": 0}

    def run_solve(self, task, workspace, solve, network, stdout_path, stderr_path):
        self.solves.append((task["image"], network, solve.name))
        return 0, "solved line\n", "stderr line\n"

    def _check(self, task, workspace):
        self.checks.append(task["image"])
        overlaid = (workspace / "answer.txt").read_text() if (workspace / "answer.txt").exists() else ""
        self.checks.append(overlaid)
        return 0, "in_task_container", "SCORE: 1.0\n" + overlaid


class Validate(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_row_shape_solve_overlay_and_no_reference(self):
        tasks = self.tmp / "tasks"
        solve = tasks / "with-solve"
        (solve / "solution").mkdir(parents=True)
        (solve / "solution" / "solve.sh").write_text("#!/bin/bash\necho ok\n")
        (solve / "checker.sh").write_text("#!/bin/bash\nexit 0\n")
        overlay = tasks / "with-overlay"
        (overlay / "solution").mkdir(parents=True)
        (overlay / "solution" / "answer.txt").write_text("golden\n")
        (overlay / "checker.sh").write_text("#!/bin/bash\nexit 0\n")
        empty = tasks / "bare"
        (empty / "solution").mkdir(parents=True)
        (empty / "solution" / ".gitkeep").write_text("")
        executor = FakeExecutor()
        out = self.tmp / "oracle.jsonl"
        rows = vr.validate_tasks(executor, [(str(tasks), "with-solve"), (str(tasks), "with-overlay"), (str(tasks), "bare")], out)
        by = {r["task"]: r for r in rows}
        solved = by["with-solve"]
        self.assertEqual(solved["status"], "pass")
        self.assertEqual(solved["checker_exit"], 0)
        self.assertTrue(solved["passed"])
        self.assertEqual(solved["image_digest"], "sha256:" + "ab" * 32)
        self.assertRegex(solved["head"], r"^[0-9a-f]{40}$")
        self.assertGreaterEqual(solved["duration_s"], 0)
        self.assertTrue(solved["stdout_tail"].endswith("solve-stdout.tail"))
        self.assertTrue(solved["stderr_tail"].endswith("solve-stderr.tail"))
        self.assertIn("solved line", (out.parent / solved["stdout_tail"]).read_text())
        self.assertTrue(solved["checker_output"].endswith("checker-stdout.tail"))
        self.assertIn("SCORE: 1.0", (out.parent / solved["checker_output"]).read_text())
        self.assertEqual(executor.solves, [("task-img:pinned", "offline", "solve.sh")])
        self.assertEqual(by["with-overlay"]["reference"], "overlay")
        self.assertEqual(by["with-overlay"]["status"], "pass")
        self.assertIn("golden\n", executor.checks)
        bare = by["bare"]
        self.assertEqual(bare["status"], "no_reference")
        self.assertIsNone(bare["checker_exit"])
        self.assertIsNone(bare["passed"])
        self.assertIsNone(bare["stdout_tail"])
        self.assertFalse((self.tmp / "trials.jsonl").exists())
        self.assertEqual(out.name, "oracle.jsonl")
        with self.assertRaises(SystemExit):
            vr.validate_tasks(executor, [(str(tasks), "bare")], self.tmp / "trials.jsonl")

    def test_solve_args_use_the_trial_network_image_and_sinkholes(self):
        executor = CellExecutor(opencode=None, project="", token=lambda: "", check_pin=False)
        task = {"dir": Path("/tmp/extract-elf"), "image": "task-img:pinned", "workdir": "/app"}
        solve = Path("/tmp/extract-elf/solution/solve.sh")
        offline = executor.solve_docker_args(task, Path("/tmp/ws"), solve, "offline")
        bridge = executor.solve_docker_args(task, Path("/tmp/ws"), solve, "bridge")
        self.assertEqual(offline[-3:], ["task-img:pinned", "bash", "/openbench-solution/solve.sh"])
        self.assertIn(OFFLINE_NETWORK, offline)
        self.assertIn(AGENT_NETWORK, bridge)
        for host in SINKHOLED_HOSTS:
            self.assertIn(f"{host}:0.0.0.0", offline)
        self.assertNotIn("opencode", " ".join(offline))

    def test_cli_no_reference_writes_oracle_jsonl(self):
        out = self.tmp / "oracle.jsonl"
        code = vr.main(["--task", "sanitize-git-repo", "--out", str(out)])
        self.assertEqual(code, 0)
        row = json.loads(out.read_text().splitlines()[0])
        self.assertEqual(row["status"], "no_reference")
        self.assertEqual(row["task"], "sanitize-git-repo")
        self.assertFalse((self.tmp / "trials.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
