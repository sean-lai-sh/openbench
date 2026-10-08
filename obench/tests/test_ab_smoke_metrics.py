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
from obench.tests.bare_python import checker_environ
from thesis.ab.evidence import (
    EXERCISED,
    NOT_EXERCISED,
    UNDETERMINABLE,
    annotate,
    attach_cell_metrics,
    child_edit_call_count,
    child_received_plan_reminder,
    classify_child_plan_reminder,
    classify_edit_only,
    classify_list_generated,
    classify_lsp_outside,
    classify_rule_order,
    dotnet_build_call_count,
    edit_call_count,
    final_answer_complete,
    load_patterns,
    members_read_metrics,
    read_call_stats,
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
        from thesis.ab.run_ab import leaked_temp_dir_names, scratch_dirs_left
        # The pre-approved scratch is not a leak. The old count treated it as
        # one and reported 0 for a real tmp.* sibling.
        self.assertEqual(leaked_temp_dirs(root), 0)
        self.assertEqual(scratch_dirs_left(root), 1)
        leaked = root / "tmp.ab12"
        leaked.mkdir()
        (leaked / "nested").mkdir()
        self.assertEqual(leaked_temp_dirs(root), 2)
        self.assertEqual(
            leaked_temp_dir_names(root),
            ["tmp.ab12", "tmp.ab12/nested"],
        )
        self.assertEqual(scratch_dirs_left(root), 1)
        evidence = Path(tempfile.mkdtemp())
        (evidence / "scratch-tmpdir.txt").write_text(str(root) + "\n", encoding="utf-8")
        recounted = attach_cell_metrics({"task": "trig-tmpdir", "tmpdir_leaked_dirs": 0}, evidence)
        self.assertEqual(recounted["tmpdir_leaked_dirs"], 2)
        self.assertEqual(recounted["tmpdir_leaked_names"], ["tmp.ab12", "tmp.ab12/nested"])
        self.assertEqual(recounted["scratch_dirs_left"], 1)
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
            env=checker_environ(env),
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
        env["OBENCH_HOST_DOTNET"] = "/no/such/obench-dotnet"
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
        env["OBENCH_HOST_DOTNET"] = "/no/such/obench-dotnet"
        proc = self._run(env, work)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("build failed", proc.stderr + proc.stdout)
        self.assertNotIn("dotnet build passed", proc.stdout)
        missing = os.environ.copy()
        missing["PATH"] = "/usr/bin:/bin"
        missing.pop("DOTNET_ROOT", None)
        missing["HOME"] = str(Path(tempfile.mkdtemp()))
        missing["OBENCH_HOST_DOTNET"] = "/no/such/obench-dotnet"
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
            ["bash", str(src / "checker.sh")], cwd=work, capture_output=True, text=True, env=checker_environ(env),
        )
        self.assertEqual(ok.returncode, 0, ok.stderr)
        outside.write_text((src / "solution" / "greeter.py").read_text(encoding="utf-8"), encoding="utf-8")
        missed = subprocess.run(
            ["bash", str(src / "checker.sh")], cwd=work, capture_output=True, text=True, env=checker_environ(env),
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


class SqliteDedupeAndScreenTests(unittest.TestCase):
    def _tool(self, name, part, **state):
        body = {"id": part, "type": "tool", "tool": name, "callID": "call-" + part, "state": state}
        return json.dumps(body)

    def test_wal_copies_and_part_ids_count_once(self):
        root = Path(tempfile.mkdtemp())
        real = "\n".join([
            self._tool("edit", "prt_e1", input={"filePath": "a.py"}),
            self._tool("edit", "prt_e2", input={"filePath": "b.py"}),
            self._tool("read", "prt_r1", input={"filePath": "catalog/members.py", "offset": 3, "limit": 5}),
            self._tool("read", "prt_r2", input={"filePath": "catalog/members.py", "offset": 4, "limit": 2}),
            self._tool("bash", "prt_b1", input={"command": "dotnet build"}),
            self._tool("bash", "prt_b2", input={"command": "dotnet build"}),
        ])
        _file(root, "part.json", real)
        # Same calls again, plus the WAL's stale page copies.
        _file(root, "agent-output.txt", real)
        wal = root / "opencode-.db-wal"
        wal.write_bytes((real + "\n").encode("utf-8") * 20 + b"\x00stale-page")
        (root / "opencode-.db-shm").write_bytes(b"\x00" * 32)
        paths = sorted(root.rglob("*"))
        paths = [path for path in paths if path.is_file()]
        self.assertEqual(edit_call_count(paths), 2)
        self.assertEqual(read_call_stats(paths), (2, True))
        self.assertEqual(dotnet_build_call_count(paths), 2)

        only = Path(tempfile.mkdtemp())
        import sqlite3
        db_path = only / "opencode-.db"
        connection = sqlite3.connect(db_path)
        connection.execute(
            "CREATE TABLE part (id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT, data TEXT)"
        )
        for part, command in (("prt_b1", "dotnet build"), ("prt_b2", "dotnet build")):
            connection.execute(
                "INSERT INTO part (id, message_id, session_id, data) VALUES (?, ?, ?, ?)",
                (part, "msg_1", "ses_root", json.dumps({
                    "type": "tool", "tool": "bash", "callID": "call-" + part,
                    "state": {"input": {"command": command}},
                })),
            )
        connection.commit()
        connection.close()
        (only / "opencode-.db-wal").write_bytes((real + "\n").encode("utf-8") * 15)
        db_paths = [path for path in only.iterdir() if path.is_file()]
        self.assertEqual(dotnet_build_call_count(db_paths), 2)
        self.assertEqual(edit_call_count(db_paths), 0)

    def test_rule_order_keeps_both_directions(self):
        self.assertEqual(classify_rule_order("GLOBAL-RULE PROJECT-RULE done"), "global_first")
        self.assertEqual(classify_rule_order("PROJECT-RULE: GLOBAL-RULE done"), "project_first")
        self.assertEqual(classify_rule_order("GLOBAL-RULE only"), "one")
        self.assertEqual(classify_rule_order("no tokens"), "none")
        root = Path(tempfile.mkdtemp())
        (root / "streamed-text.txt").write_text("PROJECT-RULE GLOBAL-RULE\n", encoding="utf-8")
        row = attach_cell_metrics({"task": "trig-prompt-order"}, root, files=[])
        self.assertEqual(row["rule_prefix"], "both")
        self.assertEqual(row["rule_order"], "project_first")

    def test_rejected_tmp_cleanup_is_present_but_not_complete(self):
        root = Path(tempfile.mkdtemp())
        text = "Fixes work. Applying to the project:"
        (root / "agent-output.txt").write_text("\n".join([
            json.dumps({
                "type": "text",
                "part": {"type": "text", "text": text, "messageID": "m1", "id": "p1", "sessionID": "ses_root"},
            }),
            "permission requested: bash (rm -rf /tmp/obench-tmp-ab12/tmp.ABCD); auto-rejecting",
            json.dumps({
                "type": "step_finish",
                "part": {"type": "step-finish", "reason": "tool-calls", "sessionID": "ses_root"},
            }),
        ]) + "\n", encoding="utf-8")
        row = attach_cell_metrics({}, root)
        self.assertTrue(row["final_answer_present"])
        self.assertIs(row["final_answer_complete"], False)
        self.assertEqual(row["final_answer_source"], "stdout")
        self.assertIs(final_answer_complete([root / "agent-output.txt"], root), False)
        stopped = Path(tempfile.mkdtemp())
        (stopped / "agent-output.txt").write_text(
            json.dumps({
                "type": "step_finish",
                "part": {"type": "step-finish", "reason": "stop", "sessionID": "ses_root"},
            }) + "\n" + json.dumps({
                "type": "text",
                "part": {"type": "text", "text": "done", "messageID": "m1", "id": "p1"},
            }) + "\n",
            encoding="utf-8",
        )
        self.assertIs(final_answer_complete([stopped / "agent-output.txt"], stopped), True)
        self.assertIs(attach_cell_metrics({}, stopped)["final_answer_complete"], True)
        self.assertEqual(attach_cell_metrics({}, stopped)["final_answer_source"], "stdout")

    def test_final_answer_comes_from_the_session_db_not_stdout(self):
        import sqlite3
        from obench.final_answer import final_answer_record, final_text

        answer = "Fixes work. Applying to the project:"
        root = Path(tempfile.mkdtemp())
        db_path = root / "opencode-.db"
        connection = sqlite3.connect(db_path)
        connection.executescript(
            """
            CREATE TABLE session (
                id TEXT PRIMARY KEY, project_id TEXT, parent_id TEXT, data TEXT
            );
            CREATE TABLE message (
                id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER, data TEXT
            );
            CREATE TABLE part (
                id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT,
                time_created INTEGER, data TEXT
            );
            """
        )
        connection.execute(
            "INSERT INTO session (id, project_id, parent_id, data) VALUES (?, ?, ?, ?)",
            ("ses_root", "proj", None, json.dumps({"id": "ses_root"})),
        )
        connection.execute(
            "INSERT INTO session (id, project_id, parent_id, data) VALUES (?, ?, ?, ?)",
            ("ses_child", "proj", "ses_root", json.dumps({"id": "ses_child", "parentID": "ses_root"})),
        )
        rows = [
            ("msg_old", "ses_root", 1, {"role": "assistant", "id": "msg_old", "sessionID": "ses_root"}),
            ("msg_last", "ses_root", 2, {"role": "assistant", "id": "msg_last", "sessionID": "ses_root"}),
            ("msg_child", "ses_child", 3, {"role": "assistant", "id": "msg_child", "sessionID": "ses_child"}),
            ("msg_user", "ses_root", 4, {"role": "user", "id": "msg_user", "sessionID": "ses_root"}),
        ]
        for ident, session, stamp, payload in rows:
            connection.execute(
                "INSERT INTO message (id, session_id, time_created, data) VALUES (?, ?, ?, ?)",
                (ident, session, stamp, json.dumps(payload)),
            )
        parts = [
            ("prt_old", "msg_old", "ses_root", 1, {"type": "text", "text": "draft"}),
            ("prt_old_fin", "msg_old", "ses_root", 2, {"type": "step-finish", "reason": "tool-calls"}),
            ("prt_text", "msg_last", "ses_root", 3, {"type": "text", "text": answer}),
            ("prt_fin", "msg_last", "ses_root", 4, {"type": "step-finish", "reason": "stop"}),
            ("prt_child", "msg_child", "ses_child", 5, {"type": "text", "text": "CHILD SHOULD NOT WIN"}),
            ("prt_child_fin", "msg_child", "ses_child", 6, {"type": "step-finish", "reason": "stop"}),
        ]
        for ident, message, session, stamp, payload in parts:
            connection.execute(
                "INSERT INTO part (id, message_id, session_id, time_created, data) VALUES (?, ?, ?, ?, ?)",
                (ident, message, session, stamp, json.dumps(payload)),
            )
        connection.commit()
        connection.close()
        # A junk WAL must not become the answer via a text scan, and stdout
        # does not contain the final text or a stop.
        (root / "opencode-.db-wal").write_bytes(
            b"STDOUT ONLY ANSWER\x00" * 8
        )
        (root / "agent-output.txt").write_text(
            "permission requested: bash (rm -rf /tmp/obench-tmp-ab12/tmp.ABCD); auto-rejecting\n"
            + json.dumps({
                "type": "step_finish",
                "part": {"type": "step-finish", "reason": "tool-calls", "sessionID": "ses_root"},
            })
            + "\n",
            encoding="utf-8",
        )
        record = final_answer_record(root)
        self.assertEqual(record["source"], "db")
        self.assertEqual(record["text"], answer)
        self.assertIs(record["complete"], True)
        self.assertEqual(final_text(root), answer)
        row = attach_cell_metrics({"task": "trig-tmpdir"}, root)
        self.assertTrue(row["final_answer_present"])
        self.assertIs(row["final_answer_complete"], True)
        self.assertEqual(row["final_answer_source"], "db")
        self.assertNotIn("CHILD SHOULD NOT WIN", final_text(root))
        self.assertNotIn("STDOUT ONLY ANSWER", final_text(root))

        # The database wins even when stdout itself ended on stop.
        cut = Path(tempfile.mkdtemp())
        cut_db = sqlite3.connect(cut / "opencode-local.db")
        cut_db.executescript(
            """
            CREATE TABLE message (
                id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER, data TEXT
            );
            CREATE TABLE part (
                id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT,
                time_created INTEGER, data TEXT
            );
            """
        )
        cut_db.execute(
            "INSERT INTO message (id, session_id, time_created, data) VALUES (?, ?, ?, ?)",
            ("msg", "ses_root", 1, json.dumps({"role": "assistant", "id": "msg"})),
        )
        cut_db.execute(
            "INSERT INTO part (id, message_id, session_id, time_created, data) VALUES (?, ?, ?, ?, ?)",
            ("p1", "msg", "ses_root", 1, json.dumps({"type": "text", "text": "still working"})),
        )
        cut_db.execute(
            "INSERT INTO part (id, message_id, session_id, time_created, data) VALUES (?, ?, ?, ?, ?)",
            ("p2", "msg", "ses_root", 2, json.dumps({"type": "step-finish", "reason": "tool-calls"})),
        )
        cut_db.commit()
        cut_db.close()
        (cut / "agent-output.txt").write_text(
            json.dumps({
                "type": "text",
                "part": {"type": "text", "text": "stdout says done", "messageID": "m1", "id": "p1"},
            }) + "\n" + json.dumps({
                "type": "step_finish",
                "part": {"type": "step-finish", "reason": "stop", "sessionID": "ses_root"},
            }) + "\n",
            encoding="utf-8",
        )
        overridden = attach_cell_metrics({}, cut)
        self.assertEqual(overridden["final_answer_source"], "db")
        self.assertEqual(final_text(cut), "still working")
        self.assertIs(overridden["final_answer_complete"], False)

    def test_read_lines_screen_metrics(self):
        line3 = "# The lending policy allows each member to hold five books at once."
        output = (
            "<path>catalog/members.py</path>\n<type>file</type>\n<content>\n"
            "3: " + line3 + "\n"
            "4: MAX_BORROWED = 3\n"
            "5: \n"
            "6: \n"
            "7: class Member:\n"
        )
        body = "\n".join([
            json.dumps({
                "id": "prt_m1", "type": "tool", "tool": "read", "callID": "c1",
                "state": {"input": {"filePath": "catalog/members.py", "offset": 3, "limit": 5}, "output": output},
            }),
            json.dumps({
                "id": "prt_m1", "type": "tool", "tool": "read", "callID": "c1",
                "state": {"input": {"filePath": "catalog/members.py", "offset": 3, "limit": 5}, "output": output},
            }),
            json.dumps({
                "id": "prt_other", "type": "tool", "tool": "read", "callID": "c2",
                "state": {"input": {"filePath": "catalog/books.py", "offset": 1, "limit": 20}},
            }),
        ])
        root = Path(tempfile.mkdtemp())
        _file(root, "part.json", body)
        (root / "opencode-.db-wal").write_bytes((body + "\n").encode("utf-8") * 10 + b"\x00")
        (root / "streamed-text.txt").write_text(line3 + "\nFixed.\n", encoding="utf-8")
        paths = [path for path in root.rglob("*") if path.is_file()]
        metrics = members_read_metrics(paths, line3 + "\nFixed.\n")
        self.assertEqual(metrics["first_read_offset"], 3)
        self.assertTrue(metrics["first_window_exact"])
        self.assertEqual(metrics["members_read_calls"], 1)
        self.assertTrue(metrics["exact_quote_pass"])
        row = attach_cell_metrics({"task": "trig-read-lines"}, root, files=paths)
        self.assertEqual(row["members_read_calls"], 1)
        self.assertTrue(row["exact_quote_pass"])
        self.assertEqual(row["first_read_offset"], 3)
        wide = _file(root, "wide.json", json.dumps({
            "id": "prt_wide", "tool": "read",
            "state": {"input": {"filePath": "catalog/members.py", "offset": 1, "limit": 20},
                      "output": "1: a\\n2: b\\n3: c\\n"},
        }))
        # The first members read is still prt_m1. A later different read does
        # not change the first window. Counting both ids yields 2.
        later = members_read_metrics([root / "part.json", wide], "")
        self.assertEqual(later["members_read_calls"], 2)
        self.assertEqual(later["first_read_offset"], 3)
        self.assertFalse(later["exact_quote_pass"])

    def test_rerun_on_sqlite_free_results_keeps_existing_columns(self):
        import csv
        import io
        from thesis.ab.prs import PullRequest
        from thesis.ab.summarize import pr_record, render_csv

        out = Path(tempfile.mkdtemp())
        pr = "3115"
        task = "trig-list"
        calls = "\n".join([
            '{"tool":"read","state":{"input":{"filePath":"src/app.py","offset":1,"limit":2}}}',
            '{"tool":"read","state":{"input":{"filePath":"src/app.py","offset":2,"limit":2}}}',
            '{"tool":"list","state":{"output":"src/app.py\\n"}}',
            '{"tool":"edit","state":{"input":{"filePath":"src/app.py"}}}',
        ])
        seeded = {
            "task": task,
            "trial": 1,
            "score": 1,
            "success": True,
            "wall_time_s": 3,
            "turns": 2,
            "tokens_output": 10,
            "tokens_input_uncached": 20,
            "tokens_cache_read": 0,
            "tokens_cache_write": 0,
        }
        patterns = load_patterns(PATTERNS)
        for side in ("without", "with"):
            cell = out / pr / "cells" / side / task / "1.json"
            cell.parent.mkdir(parents=True)
            cell.write_text(json.dumps(seeded), encoding="utf-8")
            evidence = out / pr / "transcripts" / side / task / "1"
            evidence.mkdir(parents=True)
            (evidence / "part.json").write_text(calls, encoding="utf-8")
            (evidence / "agent-output.txt").write_text(calls, encoding="utf-8")
            (out / pr / f"{side}.jsonl").write_text(json.dumps(seeded) + "\n", encoding="utf-8")
        annotate(out, patterns)
        existing = (
            "exercised", "success", "score", "read_calls", "reread", "edit_calls",
            "dotnet_build_calls", "subagent_write_calls", "child_edit_calls",
            "task_calls", "subagent_resumed", "fresh_subagents", "main_agent_searched",
            "rule_prefix", "final_answer_present", "list_has_generated",
            "permission_rejections", "ended_on_rejection", "bash_write_calls",
        )
        def cell_row(side):
            return json.loads((out / pr / "cells" / side / task / "1.json").read_text(encoding="utf-8"))

        first = {side: {key: cell_row(side).get(key) for key in existing} for side in ("without", "with")}
        self.assertEqual(first["with"]["read_calls"], 2)
        self.assertTrue(first["with"]["reread"])
        self.assertEqual(first["with"]["edit_calls"], 1)
        self.assertEqual(first["with"]["success"], True)
        self.assertEqual(first["with"]["score"], 1)
        self.assertEqual(first["with"]["exercised"], EXERCISED)
        annotate(out, patterns)
        second = {side: {key: cell_row(side).get(key) for key in existing} for side in ("without", "with")}
        self.assertEqual(second, first)
        spec = PullRequest(
            pr=pr, title="list", merged="yes",
            with_sha="a" * 40, without_sha="b" * 40,
            nearest_release="", category="tool", files_changed="", key_paths="",
            one_line="", harness_change="list", bugfix_check="",
        )
        csv_keys = (
            "without_pass_rate", "with_pass_rate", "without_mean_score", "with_mean_score",
            "without_edit_calls", "with_edit_calls", "without_final_answer", "with_final_answer",
            "without_dotnet_build_calls", "with_dotnet_build_calls",
            "without_subagent_write_calls", "with_subagent_write_calls",
            "without_rule_both", "with_rule_both", "without_rule_neither", "with_rule_neither",
        )
        def csv_existing():
            parsed = list(csv.DictReader(io.StringIO(render_csv([pr_record(spec, out)]))))[0]
            return {key: parsed[key] for key in csv_keys}

        before = csv_existing()
        self.assertEqual(before["with_edit_calls"], "1")
        self.assertEqual(before["with_pass_rate"], "1.000")
        annotate(out, patterns)
        self.assertEqual(csv_existing(), before)


def _tool_file(directory: Path, name: str, tool: str, **extra) -> Path:
    body = {"type": "tool", "tool": tool}
    body.update(extra)
    return _file(directory, name, json.dumps(body) + "\n")


class PerCallStorageTests(unittest.TestCase):
    def test_per_call_files_sum_reads_and_edits(self):
        root = Path(tempfile.mkdtemp())
        for index in range(14):
            _tool_file(
                root, f"read-{index:02d}.json", "read",
                id=f"prt_r{index}", callID=f"call-r{index}",
                state={"input": {"filePath": f"src/f{index}.py", "offset": 1, "limit": 2}},
            )
        for index in range(6):
            _tool_file(
                root, f"edit-{index:02d}.json", "edit",
                id=f"prt_e{index}", callID=f"call-e{index}",
                state={"input": {"filePath": f"src/e{index}.py"}},
            )
        paths = [path for path in sorted(root.iterdir()) if path.is_file()]
        self.assertEqual(read_call_stats(paths), (14, False))
        self.assertEqual(edit_call_count(paths), 6)
        pattern = load_patterns(PATTERNS)["984"].compiled
        self.assertEqual(classify_edit_only(paths, pattern), (EXERCISED, 6, 0))
        row = attach_cell_metrics({}, root, files=paths)
        self.assertEqual(row["read_calls"], 14)
        self.assertEqual(row["edit_calls"], 6)

    def test_same_call_in_a_per_call_file_and_a_transcript_counts_once(self):
        root = Path(tempfile.mkdtemp())
        shared = {
            "id": "prt_same", "type": "tool", "tool": "read", "callID": "call-same",
            "state": {"input": {"filePath": "src/a.py", "offset": 1}},
        }
        other = {
            "id": "prt_other", "type": "tool", "tool": "read", "callID": "call-other",
            "state": {"input": {"filePath": "src/b.py", "offset": 4}},
        }
        _file(root, "prt_same.json", json.dumps(shared) + "\n")
        _file(root, "prt_other.json", json.dumps(other) + "\n")
        _file(root, "agent-output.txt", json.dumps(shared) + "\n")
        paths = [path for path in sorted(root.iterdir()) if path.is_file()]
        self.assertEqual(read_call_stats(paths)[0], 2)
        self.assertEqual(edit_call_count(paths), 0)

        # No call id and no part id. The transcript repeats the first body,
        # so a sum would count it twice and a max-file count would stay at 1.
        plain = Path(tempfile.mkdtemp())
        first = '{"tool":"read","state":{"input":{"filePath":"src/a.py","offset":1}}}'
        second = '{"tool":"read","state":{"input":{"filePath":"src/b.py","offset":9}}}'
        _file(plain, "a.json", first + "\n")
        _file(plain, "b.json", second + "\n")
        _file(plain, "agent-output.txt", first + "\n" + first + "\n")
        plain_paths = [path for path in sorted(plain.iterdir()) if path.is_file()]
        self.assertEqual(read_call_stats(plain_paths)[0], 2)

        # Part id, no call id, transcript is a second copy of the one call.
        parted = Path(tempfile.mkdtemp())
        part = {
            "id": "prt_only", "type": "tool", "tool": "edit",
            "state": {"input": {"filePath": "src/a.py"}},
        }
        extra = {
            "id": "prt_extra", "type": "tool", "tool": "edit",
            "state": {"input": {"filePath": "src/b.py"}},
        }
        _file(parted, "prt_only.json", json.dumps(part) + "\n")
        _file(parted, "prt_extra.json", json.dumps(extra) + "\n")
        _file(parted, "transcript.txt", json.dumps(part) + "\n")
        parted_paths = [path for path in sorted(parted.iterdir()) if path.is_file()]
        self.assertEqual(edit_call_count(parted_paths), 2)

        # No id at all: file identity keeps two identical per-call bodies.
        twins = Path(tempfile.mkdtemp())
        twin = '{"tool":"edit","state":{"input":{"filePath":"src/a.py"}}}\n'
        _file(twins, "one.json", twin)
        _file(twins, "two.json", twin)
        self.assertEqual(
            edit_call_count([twins / "one.json", twins / "two.json"]),
            2,
        )

    def test_sqlite_build_counts_stay_deduped(self):
        import sqlite3
        root = Path(tempfile.mkdtemp())
        db_path = root / "opencode-.db"
        connection = sqlite3.connect(db_path)
        connection.execute(
            "CREATE TABLE part (id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT, data TEXT)"
        )
        bodies = []
        for index in range(3):
            payload = {
                "id": f"prt_r{index}", "type": "tool", "tool": "read",
                "callID": f"call-r{index}",
                "state": {"input": {"filePath": f"src/f{index}.py", "offset": 1}},
            }
            bodies.append(json.dumps(payload))
            connection.execute(
                "INSERT INTO part (id, message_id, session_id, data) VALUES (?, ?, ?, ?)",
                (f"prt_r{index}", "msg_1", "ses_root", json.dumps(payload)),
            )
        connection.commit()
        connection.close()
        text = "\n".join(bodies) + "\n"
        (root / "opencode-.db-wal").write_bytes((text.encode("utf-8")) * 20 + b"\x00stale")
        (root / "opencode-.db-shm").write_bytes(b"\x00" * 32)
        db_paths = [path for path in root.iterdir() if path.is_file()]
        self.assertEqual(read_call_stats(db_paths), (3, False))
        self.assertEqual(edit_call_count(db_paths), 0)

        # The same three calls copied into two text files must not become 6,
        # and the WAL must not multiply them.
        _file(root, "part.json", text)
        _file(root, "agent-output.txt", text)
        copied = [path for path in root.iterdir() if path.is_file()]
        self.assertEqual(read_call_stats(copied)[0], 3)
        self.assertEqual(edit_call_count(copied), 0)

    def test_other_max_file_counts_sum_split_storage(self):
        root = Path(tempfile.mkdtemp())
        _file(root, "session.json", '{"id":"ses_child","parentID":"ses_parent"}\n')
        for index in range(3):
            _tool_file(
                root, f"build-{index}.json", "bash",
                id=f"prt_b{index}", callID=f"call-b{index}",
                state={"input": {"command": "dotnet build"}},
            )
        for index in range(2):
            _tool_file(
                root, f"task-{index}.json", "task",
                id=f"prt_t{index}", callID=f"call-t{index}",
                state={"input": {"prompt": f"look {index}"}},
            )
        for index in range(2):
            _tool_file(
                root, f"child-edit-{index}.json", "edit",
                id=f"prt_c{index}", callID=f"call-c{index}",
                sessionID="ses_child",
                state={"input": {"filePath": f"child{index}.py"}},
            )
        for index in range(3):
            _file(
                root, f"reject-{index}.log",
                f"permission requested: bash (rm /tmp/x{index}); auto-rejecting\n",
            )
        outside = "/tmp/obench-shared-abc123"
        for index, name in enumerate(("one.py", "two.py")):
            _file(
                root, f"touch-{index}.log",
                f"service=lsp file={outside}/{name} touching file\n",
            )
        paths = [path for path in sorted(root.rglob("*")) if path.is_file()]
        self.assertEqual(dotnet_build_call_count(paths), 3)
        self.assertEqual(task_call_stats(paths), (2, False, 2))
        self.assertEqual(child_edit_call_count(paths), 2)
        self.assertEqual(rejection_stats(paths)[0], 3)
        from thesis.ab.evidence import outside_lsp_counts
        self.assertEqual(outside_lsp_counts(paths), (2, 0))

        # A copied aggregate log still uses the larger file, not the sum.
        copied = Path(tempfile.mkdtemp())
        log = "\n".join(
            f"service=lsp file={outside}/f{index}.py touching file" for index in range(4)
        ) + "\n"
        _file(copied, "a.log", log)
        _file(copied, "b.log", log)
        copied_paths = [path for path in copied.iterdir() if path.is_file()]
        self.assertEqual(outside_lsp_counts(copied_paths), (4, 0))


class FinalAnswerCompleteTests(unittest.TestCase):
    def test_finish_reason_is_tri_state(self):
        unknown = Path(tempfile.mkdtemp())
        (unknown / "agent-output.txt").write_text(
            json.dumps({
                "type": "text",
                "part": {"type": "text", "text": "The port is 8417.", "messageID": "m1", "id": "p1"},
            }) + "\n",
            encoding="utf-8",
        )
        self.assertIsNone(final_answer_complete([unknown / "agent-output.txt"], unknown))
        unknown_row = attach_cell_metrics({}, unknown)
        self.assertTrue(unknown_row["final_answer_present"])
        self.assertIsNone(unknown_row["final_answer_complete"])

        stopped = Path(tempfile.mkdtemp())
        (stopped / "agent-output.txt").write_text(
            json.dumps({
                "type": "text",
                "part": {"type": "text", "text": "done", "messageID": "m1", "id": "p1"},
            }) + "\n" + json.dumps({
                "type": "step_finish",
                "part": {"type": "step-finish", "reason": "stop", "sessionID": "ses_root"},
            }) + "\n",
            encoding="utf-8",
        )
        self.assertIs(final_answer_complete([stopped / "agent-output.txt"], stopped), True)

        other = Path(tempfile.mkdtemp())
        (other / "agent-output.txt").write_text(
            json.dumps({
                "type": "step_finish",
                "part": {"type": "step-finish", "reason": "length", "sessionID": "ses_root"},
            }) + "\n",
            encoding="utf-8",
        )
        self.assertIs(final_answer_complete([other / "agent-output.txt"], other), False)

        rejected = Path(tempfile.mkdtemp())
        (rejected / "agent-output.txt").write_text(
            "permission requested: bash (rm -rf /tmp/obench-tmp-ab12); auto-rejecting\n",
            encoding="utf-8",
        )
        self.assertIs(final_answer_complete([rejected / "agent-output.txt"], rejected), False)

        errored = Path(tempfile.mkdtemp())
        (errored / "agent-output.txt").write_text(
            json.dumps({"type": "text", "part": {"type": "text", "text": "partial", "messageID": "m1", "id": "p1"}})
            + "\n"
            + json.dumps({"type": "error", "error": {"type": "server_error", "message": "no_kv_space"}})
            + "\n",
            encoding="utf-8",
        )
        self.assertIs(final_answer_complete([errored / "agent-output.txt"], errored), False)
        self.assertTrue(attach_cell_metrics({}, errored)["final_answer_present"])
        self.assertIs(attach_cell_metrics({}, errored)["final_answer_complete"], False)

    def test_database_without_a_finish_reason_is_unknown(self):
        import sqlite3
        from obench.final_answer import final_answer_record

        root = Path(tempfile.mkdtemp())
        connection = sqlite3.connect(root / "opencode-.db")
        connection.executescript(
            """
            CREATE TABLE message (
                id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER, data TEXT
            );
            CREATE TABLE part (
                id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT,
                time_created INTEGER, data TEXT
            );
            """
        )
        connection.execute(
            "INSERT INTO message (id, session_id, time_created, data) VALUES (?, ?, ?, ?)",
            ("msg", "ses_root", 1, json.dumps({"role": "assistant", "id": "msg", "sessionID": "ses_root"})),
        )
        connection.execute(
            "INSERT INTO part (id, message_id, session_id, time_created, data) VALUES (?, ?, ?, ?, ?)",
            ("p1", "msg", "ses_root", 1, json.dumps({"type": "text", "text": "from the old db"})),
        )
        connection.commit()
        connection.close()
        # Stdout ended on stop. The database stored no finish reason, so the
        # cell stays unknown instead of borrowing the stdout reason or
        # treating the gap as incomplete.
        (root / "agent-output.txt").write_text(
            json.dumps({
                "type": "step_finish",
                "part": {"type": "step-finish", "reason": "stop", "sessionID": "ses_root"},
            }) + "\n",
            encoding="utf-8",
        )
        record = final_answer_record(root)
        self.assertEqual(record["source"], "db")
        self.assertEqual(record["text"], "from the old db")
        self.assertIsNone(record["complete"])
        row = attach_cell_metrics({}, root)
        self.assertEqual(row["final_answer_source"], "db")
        self.assertIsNone(row["final_answer_complete"])
        self.assertTrue(row["final_answer_present"])

    def test_summary_counts_known_cells_and_reports_unknown(self):
        known = effect_counts([
            {"final_answer_complete": True},
            {"final_answer_complete": True},
            {"final_answer_complete": False},
            {"final_answer_complete": None},
            {"final_answer_complete": None},
            {"final_answer_complete": None},
        ])
        self.assertEqual(known["final_answer_complete"], 2)
        self.assertEqual(known["final_answer_incomplete"], 1)
        self.assertEqual(known["final_answer_complete_unknown"], 3)
        absent = effect_counts([{"final_answer_present": True}])
        self.assertEqual(absent["final_answer_complete"], 0)
        self.assertEqual(absent["final_answer_incomplete"], 0)
        self.assertEqual(absent["final_answer_complete_unknown"], 0)
        line = _effect_line({
            "without": known,
            "with": effect_counts([{"final_answer_complete": False}]),
        })
        self.assertIn(
            "Final answer complete (true/false/unknown): without 2/1/3, with 0/1/0.",
            line,
        )


if __name__ == "__main__":
    unittest.main()
