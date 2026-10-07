"""Final-answer extraction, including prompt-echo fixtures that must fail."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from obench.final_answer import (
    FINAL_ANSWER_ENV,
    checker_text,
    extract_final_answer,
    publish_final_answer,
)

ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / "tasks"
COMMENT = "# The lending policy allows each member to hold five books at once."


def _event(kind, **part):
    return json.dumps({"type": kind, "part": part})


class ExtractTests(unittest.TestCase):
    def test_json_keeps_the_last_root_message_and_ignores_tools(self):
        raw = "\n".join([
            'INFO 2026 args=["quote the lending policy and the needle"]',
            _event("text", type="text", text="earlier answer", messageID="m1", sessionID="ses_root", id="p1"),
            _event("tool_use", tool="read", sessionID="ses_root", state={"output": COMMENT}),
            _event("text", type="text", text="first ", messageID="m2", sessionID="ses_root", id="p2"),
            _event("text", type="text", text="second", messageID="m2", sessionID="ses_root", id="p3"),
            _event("text", type="text", text="replaced", messageID="m2", sessionID="ses_root", id="p2"),
            '{"type":"session","id":"ses_child","parentID":"ses_root"}',
            _event("text", type="text", text="child " + COMMENT, messageID="m9", sessionID="ses_child", id="pc"),
        ])
        self.assertEqual(extract_final_answer(raw), "replacedsecond")

    def test_plain_text_drops_logs_and_tool_lines(self):
        raw = "\n".join([
            'INFO 2026 args=["' + COMMENT + '"]',
            "| Read  catalog/members.py",
            COMMENT,
        ])
        self.assertEqual(extract_final_answer(raw), COMMENT)
        echo = 'INFO 2026 args=["' + COMMENT + '"]\n| Read  catalog/members.py\n'
        self.assertNotIn(COMMENT, extract_final_answer(echo))

    def test_publish_writes_the_file_and_storage_can_fill_it(self):
        directory = Path(tempfile.mkdtemp())
        stored = directory / "message.json"
        stored.write_text(json.dumps({
            "id": "msg_1",
            "sessionID": "ses_root",
            "role": "assistant",
            "time": {"created": 10},
            "parts": [{"id": "p1", "type": "text", "text": "from storage"}],
        }), encoding="utf-8")
        saved = os.environ.get(FINAL_ANSWER_ENV)
        try:
            text = publish_final_answer(str(directory), "INFO 2026 nothing else\n")
        finally:
            if saved is None:
                os.environ.pop(FINAL_ANSWER_ENV, None)
            else:
                os.environ[FINAL_ANSWER_ENV] = saved
        self.assertEqual(text, "from storage")
        self.assertEqual((directory / "final-answer.txt").read_text(encoding="utf-8"), "from storage")

    def test_checker_text_prefers_the_evidence_dir(self):
        directory = Path(tempfile.mkdtemp())
        (directory / "agent-output.txt").write_text(
            "INFO echo\n" + _event(
                "text", type="text", text="the answer", messageID="m1", sessionID="ses_root", id="p1",
            ) + "\n",
            encoding="utf-8",
        )
        saved_dir = os.environ.get("OBENCH_OPENCODE_EVIDENCE_DIR")
        saved_path = os.environ.get(FINAL_ANSWER_ENV)
        try:
            os.environ["OBENCH_OPENCODE_EVIDENCE_DIR"] = str(directory)
            os.environ[FINAL_ANSWER_ENV] = str(directory / "missing.txt")
            self.assertEqual(checker_text(), "the answer")
        finally:
            if saved_dir is None:
                os.environ.pop("OBENCH_OPENCODE_EVIDENCE_DIR", None)
            else:
                os.environ["OBENCH_OPENCODE_EVIDENCE_DIR"] = saved_dir
            if saved_path is None:
                os.environ.pop(FINAL_ANSWER_ENV, None)
            else:
                os.environ[FINAL_ANSWER_ENV] = saved_path


class CheckerEchoTests(unittest.TestCase):
    def _run(self, src: Path, work: Path, evidence: Path | None, overlay: bool = False):
        env = os.environ.copy()
        env["TASK_DIR"] = str(src)
        env.pop("OBENCH_OPENCODE_EVIDENCE_DIR", None)
        env.pop(FINAL_ANSWER_ENV, None)
        if overlay:
            env["OPENBENCH_SOLUTION_OVERLAY"] = "1"
        elif evidence is not None:
            env["OBENCH_OPENCODE_EVIDENCE_DIR"] = str(evidence)
        return subprocess.run(
            ["bash", str(src / "checker.sh")], cwd=work, capture_output=True, text=True, env=env,
        )

    def test_read_lines_quote_must_be_in_the_final_answer(self):
        src = TASKS / "trig-read-lines"
        work = Path(tempfile.mkdtemp())
        shutil.copytree(src / "workspace", work, dirs_exist_ok=True)
        shutil.copytree(src / "solution", work, dirs_exist_ok=True)
        evidence = Path(tempfile.mkdtemp())
        (evidence / "agent-output.txt").write_text("\n".join([
            'INFO 2026 args=["quote line 3"]',
            _event("tool_use", tool="read", state={"output": COMMENT}),
            _event("text", type="text", text="All tests pass now.", messageID="m1", id="p1"),
        ]), encoding="utf-8")
        missed = self._run(src, work, evidence)
        self.assertEqual(missed.returncode, 1, missed.stderr)
        (evidence / "agent-output.txt").write_text(
            _event("text", type="text", text=COMMENT + "\nFixed.", messageID="m1", id="p1") + "\n",
            encoding="utf-8",
        )
        ok = self._run(src, work, evidence)
        self.assertEqual(ok.returncode, 0, ok.stderr)

    def test_plan_echo_of_both_keys_does_not_pass(self):
        src = TASKS / "trig-plan-subagent"
        work = Path(tempfile.mkdtemp())
        shutil.copytree(src / "workspace", work, dirs_exist_ok=True)
        evidence = Path(tempfile.mkdtemp())
        (evidence / "agent-output.txt").write_text("\n".join([
            'INFO 2026 args=["The key is written rat and should be rate."]',
            _event("tool_use", tool="read", state={"output": "settings key rat should be rate"}),
            _event("text", type="text", text="The key is rat.", messageID="m1", id="p1"),
        ]), encoding="utf-8")
        missed = self._run(src, work, evidence)
        self.assertEqual(missed.returncode, 1, missed.stdout + missed.stderr)
        (evidence / "agent-output.txt").write_text(
            _event(
                "text", type="text",
                text='The key is written "rat" and should be rate.',
                messageID="m1", id="p1",
            ) + "\n",
            encoding="utf-8",
        )
        ok = self._run(src, work, evidence)
        self.assertEqual(ok.returncode, 0, ok.stderr)

    def test_followup_list_must_be_in_the_final_answer(self):
        src = TASKS / "trig-subagent-followup"
        work = Path(tempfile.mkdtemp())
        shutil.copytree(src / "workspace", work, dirs_exist_ok=True)
        shutil.copy(src / "solution" / "settings.json", work / "settings.json")
        evidence = Path(tempfile.mkdtemp())
        listed = "See main.py, billing/report.py, and billing/export/csv_writer.py."
        (evidence / "agent-output.txt").write_text("\n".join([
            "INFO 2026 args=[\"find the fee\"]",
            _event("tool_use", tool="read", state={"output": listed}),
            _event("text", type="text", text="All tests pass now.", messageID="m1", id="p1"),
        ]), encoding="utf-8")
        missed = self._run(src, work, evidence)
        self.assertEqual(missed.returncode, 1, missed.stderr)
        (evidence / "agent-output.txt").write_text(
            _event("text", type="text", text=listed, messageID="m1", id="p1") + "\n",
            encoding="utf-8",
        )
        ok = self._run(src, work, evidence)
        self.assertEqual(ok.returncode, 0, ok.stderr)


if __name__ == "__main__":
    unittest.main()
