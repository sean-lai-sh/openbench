"""Docker-mode Harbor scoring: /app workspace mount and in-image checker.

Harbor instructions write under /app. A docker cell that bind-mounts the
workspace at /work drops those files, and run_checker used to execute
checker.sh on the host, which has no rustc. polyglot-rust-c is the case:
the reference solution must pass inside the task image, and a known-bad
answer must fail as a real verdict (checker_defect stays false).
"""

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from obench.run import (
    ROW_FIELDS,
    align_docker_workspace,
    checker_run_was_defect,
    run_cell,
)

REPO = Path(__file__).resolve().parents[2]
PACK_TASK = REPO / "data" / "packs" / "openbench-tb-hard" / "polyglot-rust-c"
IMAGE = "obench-polyglot-rustc:scoring"

DOCKERFILE = """\
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \\
      rustc g++ python3 ca-certificates curl bash \\
    && rm -rf /var/lib/apt/lists/* \\
    && mkdir -p /app \\
    && echo polyglot-task-image > /etc/openbench-checker-image
RUN curl -LsSf https://astral.sh/uv/0.9.5/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"
RUN uv python install 3.13 \\
    && uvx -p 3.13 -w pytest==8.4.1 -w pytest-json-ctrf==0.3.5 pytest --version
"""

ADAPTER = '''\
import os
import shutil

def run(instruction, workdir, model, timeout_s):
    dest = "/app/polyglot/main.rs"
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if model == "reference":
        shutil.copyfile(os.path.join(os.path.dirname(__file__), "solution.rs"), dest)
    else:
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write('fn main() { println!("0"); }\\n')
    return {
        "completed": True,
        "error": None,
        "output_tail": "workdir=%s" % workdir,
        "tokens": None,
        "turns": 1,
        "cmd": ["polywriter", workdir, model],
    }
'''


def _docker_ok():
    try:
        proc = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


class AlignDockerWorkspaceTests(unittest.TestCase):
    def test_default_mount_moves_to_app(self):
        workdir, text, rewritten = align_docker_workspace(
            "/work", "Write /app/polyglot/main.rs then `cd /app` and keep /apple.")
        self.assertEqual(workdir, "/app")
        self.assertIn("/app/polyglot/main.rs", text)
        self.assertIn("/apple", text)
        self.assertFalse(rewritten)

    def test_explicit_app_mount_is_unchanged(self):
        workdir, text, rewritten = align_docker_workspace("/app", "see /app/out")
        self.assertEqual((workdir, rewritten), ("/app", False))
        self.assertIn("/app/out", text)

    def test_custom_mount_rewrites_instruction_to_that_path(self):
        workdir, text, rewritten = align_docker_workspace(
            "/opt/src", "Write /app/polyglot/main.rs")
        self.assertEqual(workdir, "/opt/src")
        self.assertTrue(rewritten)
        self.assertIn("/opt/src/polyglot/main.rs", text)
        self.assertNotIn("/app/", text)

    def test_no_app_path_keeps_work(self):
        workdir, text, rewritten = align_docker_workspace("/work", "edit README.md")
        self.assertEqual((workdir, text, rewritten), ("/work", "edit README.md", False))

    def test_checker_defect_is_false_for_verdicts(self):
        self.assertFalse(checker_run_was_defect(0))
        self.assertFalse(checker_run_was_defect(1))
        self.assertTrue(checker_run_was_defect("timeout"))
        self.assertTrue(checker_run_was_defect(125))
        self.assertTrue(checker_run_was_defect(None))
        self.assertIn("checker_defect", ROW_FIELDS)
        self.assertEqual(ROW_FIELDS[-1], "checker_defect")


class CheckerDefectColumnTests(unittest.TestCase):
    def _cell(self, exit_code):
        root = tempfile.mkdtemp(prefix="obench-defect-")
        self.addCleanup(shutil.rmtree, root, True)
        task = os.path.join(root, "tasks", "tiny")
        os.makedirs(os.path.join(task, "workspace"))
        with open(os.path.join(task, "instruction.md"), "w", encoding="utf-8") as fh:
            fh.write("do nothing\n")
        checker = os.path.join(task, "checker.sh")
        with open(checker, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\nexit %d\n" % exit_code)
        os.chmod(checker, os.stat(checker).st_mode | stat.S_IXUSR)
        return run_cell(
            "null", "tiny", "m", 1, 30,
            os.path.join(root, "tasks"), os.path.join(root, "adapters"), 30,
            exec_mode="local",
        )

    def test_pass_and_fail_verdicts_are_not_defects(self):
        passed = self._cell(0)
        failed = self._cell(1)
        self.assertIs(passed["checker_defect"], False)
        self.assertTrue(passed["success"])
        self.assertIs(failed["checker_defect"], False)
        self.assertFalse(failed["success"])

    def test_non_verdict_exit_is_a_checker_defect(self):
        row = self._cell(7)
        self.assertIs(row["checker_defect"], True)
        self.assertFalse(row["success"])
        self.assertEqual(row["checker_exit"], 7)

    def test_append_keeps_existing_rows(self):
        from obench.run import append_row
        root = tempfile.mkdtemp(prefix="obench-append-")
        self.addCleanup(shutil.rmtree, root, True)
        path = os.path.join(root, "results.jsonl")
        prior = '{"run_id": "old", "success": true}\n'
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(prior)
        row = {field: None for field in ROW_FIELDS}
        row["run_id"] = "new"
        row["checker_defect"] = False
        self.assertTrue(append_row(path, row))
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
        self.assertEqual(lines[0], prior)
        self.assertIn('"checker_defect": false', lines[1])
        self.assertIn('"run_id": "old"', lines[0])


@unittest.skipUnless(_docker_ok(), "docker daemon is not available")
class PolyglotDockerCellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        probe = subprocess.run(
            ["docker", "image", "inspect", IMAGE],
            capture_output=True, text=True, timeout=30,
        )
        if probe.returncode != 0:
            ctx = tempfile.mkdtemp(prefix="obench-polyglot-image-")
            try:
                with open(os.path.join(ctx, "Dockerfile"), "w", encoding="utf-8") as fh:
                    fh.write(DOCKERFILE)
                built = subprocess.run(
                    ["docker", "build", "-t", IMAGE, ctx],
                    capture_output=True, text=True, timeout=900,
                )
            finally:
                shutil.rmtree(ctx, ignore_errors=True)
            if built.returncode != 0:
                raise unittest.SkipTest(
                    "could not build %s: %s" % (IMAGE, (built.stderr or "")[-400:])
                )

    def _task(self, root):
        task = os.path.join(root, "tasks", "polyglot-rust-c")
        shutil.copytree(PACK_TASK, task)
        with open(os.path.join(task, "task.toml"), "w", encoding="utf-8") as fh:
            fh.write('docker_image = "%s"\n' % IMAGE)
        checker = os.path.join(task, "checker.sh")
        text = Path(checker).read_text(encoding="utf-8")
        needle = 'cleanup() { rm -rf "${REWARD_DIR}" "${RUN_DIR}"; }'
        # The script's own EXIT trap replaces any earlier trap. Print the
        # image marker from that cleanup so it is the last stdout line and
        # survives the runner's tail capture.
        marker = (
            'cleanup() { echo "OBENCH_CHECKER_ENV=$(cat /etc/openbench-checker-image '
            '2>/dev/null || echo host)"; rm -rf "${REWARD_DIR}" "${RUN_DIR}"; }'
        )
        if needle not in text:
            raise AssertionError("polyglot checker.sh lost its cleanup trap")
        Path(checker).write_text(text.replace(needle, marker, 1), encoding="utf-8")
        adapters = os.path.join(root, "adapters")
        os.makedirs(adapters)
        with open(os.path.join(adapters, "polywriter.py"), "w", encoding="utf-8") as fh:
            fh.write(ADAPTER)
        shutil.copyfile(
            PACK_TASK / "solution" / "polyglot" / "main.rs",
            os.path.join(adapters, "solution.rs"),
        )
        return adapters

    def _run(self, model):
        root = tempfile.mkdtemp(prefix="obench-polyglot-cell-")
        self.addCleanup(shutil.rmtree, root, True)
        adapters = self._task(root)
        return run_cell(
            "polywriter", "polyglot-rust-c", model, 1, 120,
            os.path.join(root, "tasks"), adapters, 300,
            exec_mode="docker", docker_fallback=False,
        )

    def test_reference_solution_passes_inside_task_image(self):
        row = self._run("reference")
        self.assertEqual(row["exec_mode"], "docker", row.get("error"))
        self.assertIn("workdir=/app", row.get("output_tail") or "", row.get("error"))
        self.assertIn("polyglot/main.rs", row.get("checker_workspace_files") or {})
        self.assertIn("OBENCH_CHECKER_ENV=polyglot-task-image", row.get("checker_stdout") or "")
        self.assertNotIn("command not found", row.get("checker_stdout") or "")
        self.assertEqual(row["checker_exit"], 0, row.get("checker_stdout"))
        self.assertTrue(row["success"])
        self.assertEqual(row["score"], 1.0)
        self.assertIs(row["checker_defect"], False)

    def test_known_bad_answer_fails(self):
        row = self._run("bad")
        self.assertEqual(row["exec_mode"], "docker", row.get("error"))
        self.assertIn("workdir=/app", row.get("output_tail") or "")
        self.assertIn("polyglot/main.rs", row.get("checker_workspace_files") or {})
        self.assertIn("OBENCH_CHECKER_ENV=polyglot-task-image", row.get("checker_stdout") or "")
        self.assertNotIn("command not found", (row.get("checker_stdout") or "") + (row.get("checker_stderr") or ""))
        self.assertEqual(row["checker_exit"], 1, row.get("checker_stdout"))
        self.assertFalse(row["success"])
        self.assertEqual(row["score"], 0.0)
        self.assertIs(row["checker_defect"], False)


if __name__ == "__main__":
    unittest.main()
