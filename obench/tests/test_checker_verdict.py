"""Thesis checkers agree on exit code and OBENCH_VERDICT, or the cell is infra."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from obench.checker_verdict import (
    VERDICT_FAIL,
    VERDICT_PASS,
    apply_explicit_verdict,
    expects_explicit_verdict,
    verdict_agrees,
)
from obench.failure_class import class_for_report, classify_failure, classify_failure_reason
from obench.tests.bare_python import bare_python_bin, checker_environ

ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / "tasks"
COMMENT = "# The lending policy allows each member to hold five books at once."


def _graded(**extra):
    row = {
        "task": "trig-read-lines",
        "harness": "opencode",
        "completed": True,
        "turns": 4,
        "tokens_output": 40,
        "checker_stdout": "",
        "checker_stderr": "",
    }
    row.update(extra)
    return row


class VerdictProtocolTests(unittest.TestCase):
    def test_import_failure_is_infra_not_a_wrong_answer(self):
        row = _graded(checker_stderr=(
            "Traceback (most recent call last):\n"
            "  File \"checker.sh\", line 1, in <module>\n"
            "ModuleNotFoundError: No module named 'obench'\n"
        ))
        apply_explicit_verdict(
            row, 1, None, classify_failure, classify_failure_reason,
        )
        self.assertFalse(row["success"])
        self.assertEqual(row["failure_class"], "infra")
        self.assertIn("ModuleNotFoundError", row["failure_reason"])
        self.assertTrue(row["failure_reason"].startswith("checker_crash"))
        self.assertEqual(class_for_report(row), "infra")

    def test_exit_127_is_infra(self):
        row = _graded(checker_stderr="bash: python3: command not found\n")
        apply_explicit_verdict(
            row, 127, None, classify_failure, classify_failure_reason,
        )
        self.assertEqual(row["failure_class"], "infra")
        self.assertIn("127", row["failure_reason"])
        self.assertEqual(class_for_report(row), "infra")

    def test_real_wrong_answer_stays_fail(self):
        row = _graded(checker_stdout="FAIL: missing quote\n" + VERDICT_FAIL + "\n")
        apply_explicit_verdict(
            row, 1, None, classify_failure, classify_failure_reason,
        )
        self.assertFalse(row["success"])
        self.assertEqual(row["failure_class"], "wrong_answer")
        self.assertTrue(verdict_agrees(1, row["checker_stdout"]))

    def test_real_correct_answer_stays_pass(self):
        row = _graded(checker_stdout="quoted\n" + VERDICT_PASS + "\n")
        apply_explicit_verdict(
            row, 0, None, classify_failure, classify_failure_reason,
        )
        self.assertTrue(row["success"])
        self.assertEqual(row["score"], 1.0)
        self.assertEqual(row["failure_class"], "solved")

    def test_imported_graders_do_not_require_a_verdict_line(self):
        self.assertFalse(expects_explicit_verdict("/opt/tasks-imported/terminal-bench/cancel-async-tasks"))
        self.assertTrue(expects_explicit_verdict(str(TASKS / "trig-read-lines")))
        self.assertTrue(expects_explicit_verdict(str(TASKS / "make-it-run")))


class BareCheckerTests(unittest.TestCase):
    def test_bare_python_cannot_import_obench(self):
        env = checker_environ()
        probe = subprocess.run(
            [str(bare_python_bin() / "python3"), "-c", "import obench"],
            cwd="/tmp",
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(probe.returncode, 0, probe.stdout + probe.stderr)
        self.assertIn("No module named", probe.stderr)

    def _run(self, src: Path, work: Path, env: dict):
        merged = checker_environ(env)
        self.assertNotIn("PYTHONPATH", merged)
        return subprocess.run(
            ["bash", str(src / "checker.sh")],
            cwd=work,
            env=merged,
            capture_output=True,
            text=True,
        )

    def test_three_checkers_grade_without_an_install(self):
        # trig-read-lines: tests pass, quote missing, then quote present.
        src = TASKS / "trig-read-lines"
        work = Path(tempfile.mkdtemp())
        shutil.copytree(src / "workspace", work, dirs_exist_ok=True)
        shutil.copytree(src / "solution", work, dirs_exist_ok=True)
        evidence = Path(tempfile.mkdtemp())
        (evidence / "agent-output.txt").write_text("All tests pass now.\n", encoding="utf-8")
        env = os.environ.copy()
        env["TASK_DIR"] = str(src)
        env["OBENCH_OPENCODE_EVIDENCE_DIR"] = str(evidence)
        missed = self._run(src, work, env)
        self.assertEqual(missed.returncode, 1, missed.stderr)
        self.assertIn(VERDICT_FAIL, missed.stdout)
        (evidence / "agent-output.txt").write_text(COMMENT + "\nFixed.\n", encoding="utf-8")
        ok = self._run(src, work, env)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertIn(VERDICT_PASS, ok.stdout)

        # trig-plan-subagent: unchanged workspace, both keys only in the final answer.
        src = TASKS / "trig-plan-subagent"
        work = Path(tempfile.mkdtemp())
        shutil.copytree(src / "workspace", work, dirs_exist_ok=True)
        evidence = Path(tempfile.mkdtemp())
        (evidence / "agent-output.txt").write_text(
            'The key is written "rat" and should be rate.\n',
            encoding="utf-8",
        )
        env = {"TASK_DIR": str(src), "OBENCH_OPENCODE_EVIDENCE_DIR": str(evidence), "PATH": os.environ.get("PATH", "")}
        planned = self._run(src, work, env)
        self.assertEqual(planned.returncode, 0, planned.stderr)
        self.assertIn(VERDICT_PASS, planned.stdout)
        (work / "settings.json").write_text('{"rate": 0.5}\n', encoding="utf-8")
        changed = self._run(src, work, env)
        self.assertEqual(changed.returncode, 1, changed.stdout + changed.stderr)
        self.assertIn(VERDICT_FAIL, changed.stdout)

        # trig-subagent-followup: program fixed, list present, then omitted.
        src = TASKS / "trig-subagent-followup"
        work = Path(tempfile.mkdtemp())
        shutil.copytree(src / "workspace", work, dirs_exist_ok=True)
        shutil.copy(src / "solution" / "settings.json", work / "settings.json")
        evidence = Path(tempfile.mkdtemp())
        listed = "See main.py, billing/report.py, and billing/export/csv_writer.py.\n"
        (evidence / "agent-output.txt").write_text(listed, encoding="utf-8")
        env = {
            "TASK_DIR": str(src),
            "OBENCH_OPENCODE_EVIDENCE_DIR": str(evidence),
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", "/tmp"),
        }
        found = self._run(src, work, env)
        self.assertEqual(found.returncode, 0, found.stderr)
        self.assertIn(VERDICT_PASS, found.stdout)
        (evidence / "agent-output.txt").write_text("only main.py\n", encoding="utf-8")
        missed = self._run(src, work, env)
        self.assertEqual(missed.returncode, 1, missed.stderr)
        self.assertIn(VERDICT_FAIL, missed.stdout)


if __name__ == "__main__":
    unittest.main()
