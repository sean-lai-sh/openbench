"""Smoke-audit metrics and the rewritten C# checker."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from obench.validate_tasks import checker_column, sdk_missing_polarity
from thesis.ab.evidence import (
    EXERCISED,
    NOT_EXERCISED,
    UNDETERMINABLE,
    annotate,
    attach_cell_metrics,
    child_edit_call_count,
    child_received_plan_reminder,
    classify_child_plan_reminder,
    classify_list_generated,
    classify_lsp_outside,
    dotnet_build_call_count,
    edit_call_count,
    load_patterns,
    rejection_stats,
    subagent_write_call_count,
    task_call_stats,
)
from thesis.ab.run_ab import ensure_empty_opencode, leaked_temp_dirs, scratch_env
from thesis.ab.summarize import _effect_line, effect_counts

ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / "tasks"
PATTERNS = ROOT / "thesis" / "ab" / "fixtures" / "trigger-evidence.csv"
CHECK = TASKS / "trig-lsp-csharp" / "checker_data" / "check.py"


def _file(directory: Path, name: str, text: str) -> Path:
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


class ResumeDetectionTests(unittest.TestCase):
    def test_4204_structured_metadata_still_counts_as_resumed(self):
        directory = Path(tempfile.mkdtemp())
        path = _file(directory, "part.json", "\n".join([
            '{"tool":"task","state":{"input":{"prompt":"look"},"metadata":{"session_id":"ses_child"}}}',
            '{"tool":"task","state":{"input":{"session_id":"ses_child","prompt":"continue"}}}',
        ]))
        self.assertEqual(task_call_stats([path]), (2, True, 1))

    def test_12214_plain_text_session_id_counts_as_resumed(self):
        directory = Path(tempfile.mkdtemp())
        path = _file(directory, "part.json", "\n".join([
            '{"tool":"task","state":{"status":"completed","input":{"prompt":"look"},'
            '"output":"task_id: ses_resume01 (for resuming to continue this task)\\n'
            '<task_result>done</task_result>"}}',
            '{"tool":"task","state":{"input":{"task_id":"ses_resume01","prompt":"continue"}}}',
        ]))
        self.assertEqual(task_call_stats([path]), (2, True, 1))
        only = _file(directory, "once.json", (
            '{"tool":"task","state":{"output":"task_id: ses_resume01 (for resuming...)"}}'
        ))
        self.assertEqual(task_call_stats([only]), (1, False, 1))


class ListAndPlanMetricTests(unittest.TestCase):
    def test_generated_in_list_output_is_the_2367_trigger(self):
        directory = Path(tempfile.mkdtemp())
        present = _file(directory, "present.json", (
            '{"tool":"list","state":{"output":"src/app.py\\ngenerated/one.py\\n"}}'
        ))
        absent = _file(directory, "absent.json", (
            '{"tool":"list","state":{"output":"src/app.py\\ntests/test_app.py\\n"}}'
        ))
        self.assertEqual(classify_list_generated([present]), (EXERCISED, True))
        self.assertEqual(classify_list_generated([absent]), (NOT_EXERCISED, False))
        self.assertEqual(classify_list_generated([]), (UNDETERMINABLE, False))
        pattern = load_patterns(PATTERNS)["23771"].compiled
        self.assertIsNotNone(pattern.search("LSP errors detected in Program.cs"))
        self.assertIsNotNone(pattern.search(
            'LSP errors detected in this file, please fix:\\n<diagnostics file="Program.cs"'
        ))

    def test_child_plan_reminder_ignores_the_parent_and_bash(self):
        directory = Path(tempfile.mkdtemp())
        parent_only = _file(directory, "parent.json", "\n".join([
            '{"id":"ses_child","parentID":"ses_parent"}',
            '{"sessionID":"ses_parent","text":"Plan mode is active. The user indicated that they do not want you to execute yet."}',
        ]))
        self.assertFalse(child_received_plan_reminder([parent_only]))
        self.assertEqual(classify_child_plan_reminder([parent_only]), (NOT_EXERCISED, False))
        child = _file(directory, "child.json", "\n".join([
            '{"id":"ses_child","parentID":"ses_parent"}',
            '{"sessionID":"ses_child","text":"Plan mode is active. The user indicated that they do not want you to execute yet."}',
            '{"tool":"edit","sessionID":"ses_child","state":{"input":{"filePath":"settings.json"}}}',
            '{"tool":"bash","sessionID":"ses_child","state":{"input":{"command":"python3 main.py"}}}',
        ]))
        builds = _file(directory, "builds.json", "\n".join([
            '{"tool":"bash","state":{"input":{"command":"dotnet build"}}}',
            '{"tool":"edit","state":{"input":{"filePath":"Program.cs"}}}',
            '{"tool":"edit","state":{"input":{"filePath":"Program.cs"}}}',
        ]))
        self.assertTrue(child_received_plan_reminder([child]))
        self.assertEqual(child_edit_call_count([child, builds]), 1)
        self.assertEqual(subagent_write_call_count([child, builds]), 2)
        self.assertEqual(dotnet_build_call_count([child, builds]), 1)
        self.assertEqual(edit_call_count([child, builds]), 2)

    def test_summary_names_bash_in_subagent_writes_and_rolls_up_metrics(self):
        effects = {
            "without": effect_counts([{
                "subagent_write_calls": 3,
                "child_edit_calls": 1,
                "child_plan_reminder": False,
                "workspace_changed": True,
                "list_has_generated": True,
                "dotnet_build_calls": 2,
                "edit_calls": 4,
                "permission_rejections": 1,
                "ended_on_rejection": True,
                "final_answer_present": False,
                "tmpdir_leaked_dirs": 2,
            }]),
            "with": effect_counts([{
                "subagent_write_calls": 0,
                "child_edit_calls": 0,
                "child_plan_reminder": True,
                "workspace_changed": False,
                "list_has_generated": False,
                "dotnet_build_calls": 0,
                "edit_calls": 1,
                "permission_rejections": 0,
                "ended_on_rejection": False,
                "final_answer_present": True,
                "tmpdir_leaked_dirs": 0,
            }]),
        }
        line = _effect_line(effects)
        self.assertIn("bash+edit+write+patch", line)
        self.assertIn("Child edit/write/patch (not bash): without 1, with 0", line)
        self.assertIn("Child plan-mode reminder: without 0, with 1", line)
        self.assertIn("Workspace changed: without 1, with 0", line)
        self.assertIn("generated/: without 1, with 0", line)
        self.assertIn("dotnet build calls: without 2, with 0", line)
        self.assertIn("Permission rejections: without 1, with 0", line)
        self.assertIn("Ended on rejection: without 1, with 0", line)
        self.assertIn("Final answer present: without 0, with 1", line)
        self.assertIn("Leaked temp dirs: without 2, with 0", line)


class TmpdirMetricTests(unittest.TestCase):
    def test_rejections_final_answer_and_an_empty_opencode_dir(self):
        directory = Path(tempfile.mkdtemp())
        rejected = _file(directory, "agent-output.txt", (
            'permission requested: external_directory (/tmp/obench-tmp-abc/opencode); auto-rejecting\n'
        ))
        count, ended = rejection_stats([rejected])
        self.assertEqual(count, 1)
        self.assertTrue(ended)
        answered = _file(directory, "later.json", "\n".join([
            'permission requested: external_directory (/tmp/x); auto-rejecting',
            '{"type":"text","part":{"type":"text","text":"Hello, world!","messageID":"m1"}}',
        ]))
        count, ended = rejection_stats([answered])
        self.assertEqual(count, 1)
        self.assertFalse(ended)
        reminded = _file(directory, "plan-after.txt", (
            "auto-rejecting\nPlan mode is active.\n"
        ))
        count, ended = rejection_stats([reminded])
        self.assertEqual(count, 1)
        self.assertTrue(ended)
        root = Path(tempfile.mkdtemp())
        (root / "opencode").mkdir()
        (root / "opencode" / "stale.txt").write_text("old", encoding="utf-8")
        (root / "opencode" / "nested").mkdir()
        emptied = ensure_empty_opencode(root)
        self.assertEqual(list(emptied.iterdir()), [])
        self.assertEqual(leaked_temp_dirs(root), 0)
        (emptied / "scratch").mkdir()
        self.assertEqual(leaked_temp_dirs(root), 1)
        env = scratch_env({"task": "trig-tmpdir"})
        self.addCleanup(lambda: __import__("shutil").rmtree(env["TMPDIR"], ignore_errors=True))
        opencode = Path(env["TMPDIR"]) / "opencode"
        self.assertTrue(opencode.is_dir())
        self.assertEqual(list(opencode.iterdir()), [])
        self.assertEqual(env["TMPDIR"], env["TMP"])
        pattern = load_patterns(PATTERNS)["25226"].compiled
        self.assertIsNotNone(pattern.search(
            '{"tool":"write","state":{"input":{"filePath":"/tmp/obench-tmp-ab12/opencode/note.txt"}}}'
        ))
        self.assertIsNone(pattern.search(
            '{"tool":"write","state":{"input":{"filePath":"greeter.py"}}}'
        ))
        self.assertIsNone(pattern.search(
            '{"tool":"read","state":{"input":{"filePath":"/tmp/opencode/note.txt"}}}'
        ))
        prompt = (TASKS / "trig-tmpdir" / "instruction.md").read_text(encoding="utf-8")
        self.assertNotIn("/tmp/opencode", prompt)

    def test_annotate_uses_generated_and_the_plan_reminder_as_triggers(self):
        out = Path(tempfile.mkdtemp())

        def plant(pr, side, task, body):
            cell = out / pr / "cells" / side / task / "1.json"
            cell.parent.mkdir(parents=True)
            cell.write_text(json.dumps({"task": task, "trial": 1}), encoding="utf-8")
            evidence = out / pr / "transcripts" / side / task / "1" / "part.json"
            evidence.parent.mkdir(parents=True)
            evidence.write_text(body, encoding="utf-8")

        plant("2367", "without", "trig-list-noise",
              '{"tool":"list","state":{"output":"generated/one.py\\n"}}')
        plant("2367", "with", "trig-list-noise",
              '{"tool":"list","state":{"output":"src/app.py\\n"}}')
        plant("1248", "with", "trig-plan-subagent", "\n".join([
            '{"id":"ses_child","parentID":"ses_parent"}',
            '{"sessionID":"ses_child","text":"Plan mode is active."}',
        ]))
        plant("1248", "without", "trig-plan-subagent", "\n".join([
            '{"id":"ses_child","parentID":"ses_parent"}',
            '{"sessionID":"ses_parent","text":"Plan mode is active."}',
        ]))
        annotate(out, load_patterns(PATTERNS))
        without = json.loads((out / "2367" / "cells" / "without" / "trig-list-noise" / "1.json").read_text())
        merged = json.loads((out / "2367" / "cells" / "with" / "trig-list-noise" / "1.json").read_text())
        self.assertEqual(without["exercised"], EXERCISED)
        self.assertTrue(without["list_has_generated"])
        self.assertEqual(merged["exercised"], NOT_EXERCISED)
        self.assertFalse(merged["list_has_generated"])
        reminded = json.loads((out / "1248" / "cells" / "with" / "trig-plan-subagent" / "1.json").read_text())
        missed = json.loads((out / "1248" / "cells" / "without" / "trig-plan-subagent" / "1.json").read_text())
        self.assertEqual(reminded["exercised"], EXERCISED)
        self.assertTrue(reminded["child_plan_reminder"])
        self.assertEqual(missed["exercised"], NOT_EXERCISED)
        self.assertFalse(missed["child_plan_reminder"])
        empty = Path(tempfile.mkdtemp())
        row = attach_cell_metrics({"task": "trig-list-noise"}, empty, files=[])
        self.assertIsNone(row["list_has_generated"])


class CSharpCheckerTests(unittest.TestCase):
    def _fake(self, directory: Path, code: str) -> Path:
        path = directory / "dotnet"
        path.write_text(textwrap.dedent(f"""\
            #!/usr/bin/env python3
            import os, pathlib, sys
            log = os.environ.get("FAKE_DOTNET_LOG")
            if log:
                pathlib.Path(log).write_text(os.environ.get("DOTNET_CLI_HOME", ""), encoding="utf-8")
            sys.stderr.write("build failed\\n")
            raise SystemExit({code})
        """), encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
        return path

    def _run(self, env, work: Path):
        return subprocess.run(
            [sys.executable, str(CHECK)],
            cwd=work,
            env=env,
            capture_output=True,
            text=True,
        )

    def test_dotnet_root_is_used_when_path_has_no_sdk(self):
        work = Path(tempfile.mkdtemp())
        root = Path(tempfile.mkdtemp())
        log = Path(tempfile.mkdtemp()) / "log.txt"
        self._fake(root, "0")
        env = os.environ.copy()
        env["PATH"] = "/usr/bin:/bin"
        env["DOTNET_ROOT"] = str(root)
        env["HOME"] = "/no/such/home"
        env["FAKE_DOTNET_LOG"] = str(log)
        env.pop("DOTNET_CLI_HOME", None)
        proc = self._run(env, work)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("dotnet build passed", proc.stdout)
        self.assertTrue(log.is_file())
        self.assertTrue(Path(log.read_text(encoding="utf-8").strip()).is_dir())

    def test_path_beats_dotnet_root_and_a_missing_sdk_exits_2(self):
        work = Path(tempfile.mkdtemp())
        path_root = Path(tempfile.mkdtemp())
        other = Path(tempfile.mkdtemp())
        self._fake(path_root, "1")
        good = other / "dotnet"
        good.write_text("#!/bin/sh\necho should-not-run\nexit 0\n", encoding="utf-8")
        good.chmod(good.stat().st_mode | stat.S_IEXEC)
        env = os.environ.copy()
        env["PATH"] = os.pathsep.join([str(path_root), "/usr/bin", "/bin"])
        env["DOTNET_ROOT"] = str(other)
        env["HOME"] = str(Path(tempfile.mkdtemp()))
        proc = self._run(env, work)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("build failed", proc.stderr + proc.stdout)
        self.assertNotIn("dotnet build passed", proc.stdout)
        missing = os.environ.copy()
        missing["PATH"] = "/usr/bin:/bin"
        missing.pop("DOTNET_ROOT", None)
        missing["HOME"] = str(Path(tempfile.mkdtemp()))
        gone = self._run(missing, work)
        self.assertEqual(gone.returncode, 2)
        self.assertIn("dotnet SDK was not found", gone.stderr)
        message = "dotnet SDK was not found; the checker cannot run dotnet build"
        self.assertTrue(sdk_missing_polarity(2, message, 2, message))
        self.assertFalse(sdk_missing_polarity(1, message, 0, "dotnet build passed"))
        self.assertEqual(checker_column(2, solution=False, sdk_missing=True), "infra")
        self.assertEqual(checker_column(2, solution=True, sdk_missing=True), "infra")
        self.assertEqual(checker_column(1, solution=False, sdk_missing=False), "FAIL(ok)")
        self.assertEqual(checker_column(0, solution=True, sdk_missing=False), "PASS(ok)")


class OutsideAndAnswerTests(unittest.TestCase):
    def test_outside_lsp_classifier_requires_touch_without_a_client(self):
        outside = "/tmp/obench-shared-abc123/greeter_copy.py"
        parent = "\n".join([
            f"service=lsp file={outside} touching file",
            f"lsp.client serverID=pyright path={outside} method=textDocument/didOpen",
        ])
        merged = f"service=lsp file={outside} touching file\n"
        directory = Path(tempfile.mkdtemp())
        parent_path = _file(directory, "parent.log", parent)
        merged_path = _file(directory, "merged.log", merged)
        status, touches, clients = classify_lsp_outside([parent_path])
        self.assertEqual(status, NOT_EXERCISED)
        self.assertGreater(clients, 0)
        self.assertGreaterEqual(touches, 1)
        status, touches, clients = classify_lsp_outside([merged_path])
        self.assertEqual(status, EXERCISED)
        self.assertEqual(clients, 0)
        self.assertEqual(classify_lsp_outside([])[0], UNDETERMINABLE)

    def test_greeter_copy_matches_the_cell_file(self):
        src = TASKS / "trig-lsp-outside"
        work = Path(tempfile.mkdtemp())
        for name in ("main.py", "greeter.py"):
            (work / name).write_text((src / "solution" / name).read_text(encoding="utf-8"), encoding="utf-8")
        (work / "greeter.py").write_text(
            (work / "greeter.py").read_text(encoding="utf-8") + "\n# cell edit\n",
            encoding="utf-8",
        )
        outside = Path(tempfile.mkdtemp()) / "greeter_copy.py"
        outside.write_text((work / "greeter.py").read_text(encoding="utf-8"), encoding="utf-8")
        env = os.environ.copy()
        env["TASK_DIR"] = str(src)
        env["OBENCH_OPENCODE_OUTSIDE_PATH"] = str(outside)
        ok = subprocess.run(
            ["bash", str(src / "checker.sh")], cwd=work, capture_output=True, text=True, env=env,
        )
        self.assertEqual(ok.returncode, 0, ok.stderr)
        outside.write_text((src / "solution" / "greeter.py").read_text(encoding="utf-8"), encoding="utf-8")
        missed = subprocess.run(
            ["bash", str(src / "checker.sh")], cwd=work, capture_output=True, text=True, env=env,
        )
        self.assertEqual(missed.returncode, 1)

    def test_fillers_are_not_one_template(self):
        billing = TASKS / "trig-subagent-followup" / "workspace" / "billing"
        bodies = [
            path.read_text(encoding="utf-8")
            for path in billing.glob("*.py")
            if path.name not in {"__init__.py", "report.py"}
        ]
        self.assertEqual(len(bodies), 25)
        self.assertEqual(len(set(bodies)), 25)
        self.assertFalse(any("SLOT" in body for body in bodies))
        hits = []
        for path in (TASKS / "trig-subagent-followup" / "workspace").rglob("*.py"):
            if "fee_" in path.read_text(encoding="utf-8"):
                hits.append(path.name)
        self.assertGreater(len(hits), 3)


if __name__ == "__main__":
    unittest.main()
