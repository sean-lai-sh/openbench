"""Trigger-task copies and the evidence-pattern grep."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from thesis.ab.evidence import (
    DEFAULT_PATTERNS,
    EXERCISED,
    NOT_EXERCISED,
    UNDETERMINABLE,
    annotate,
    classify_edit_only,
    load_patterns,
    main,
)
from thesis.ab.run_ab import load_task_map

ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / "tasks"
PATTERNS = ROOT / "thesis" / "ab" / "fixtures" / "trigger-evidence.csv"
TASK_MAP = ROOT / "thesis" / "ab" / "fixtures" / "trigger-tasks.csv"

COPIES = {
    "trig-list": "add-feature",
    "trig-subagent-resume": "misleading-error",
    "trig-bash-limits": "fix-failing-test",
    "trig-workdir": "misleading-error",
    "trig-read-edge": "make-ci-green",
    "trig-grep-trunc": "taskflow",
    "trig-todo-task": "make-ci-green",
    "trig-plan-subagent": "misleading-error",
    "trig-tmpdir": "make-it-run",
    "trig-lsp-outside": "make-it-run",
}
PREFIXES = {
    "trig-list": "Start by listing the project with the list tool.",
    "trig-subagent-resume": (
        "Use the task tool to have a general subagent trace where `rate` becomes None "
        "and report the file and line. Then call the task tool again, passing the id the "
        "first call returned so the same subagent continues, and ask it which settings key "
        "is missing. Then fix the bug yourself."
    ),
    "trig-bash-limits": (
        "Before fixing anything, run these two diagnostics with the bash tool exactly as written: "
        '(1) `python3 -c "print(\'diag \' * 8000)"` (about 40,000 chars); '
        "(2) `sleep 5 && python3 -m unittest` with the bash tool's timeout parameter set to 2000. "
        "Then fix the bug."
    ),
    "trig-workdir": (
        "First run `python3 -c 'import pricing; print(pricing.__file__)'` with the `app/` "
        "directory as the working directory."
    ),
    "trig-read-edge": (
        "Before fixing anything: (a) use the read tool on the `catalog/` directory itself; "
        "(b) read `catalog/books.py` with offset 0 and limit 5; (c) read `catalog/books.py` "
        "with offset 3 and limit 5. Then fix the failing tests."
    ),
    "trig-grep-trunc": "Start by using the grep tool to search for `self` across the project.",
    "trig-todo-task": (
        "Track your work with the todo list tool, and delegate investigation of at least one "
        "failing test file to a subagent with the task tool."
    ),
    "trig-plan-subagent": (
        "Use the task tool to have a subagent find which settings key `rate` should come from "
        "and report the file and line. Then fix the bug."
    ),
    "trig-tmpdir": (
        "Do any scratch work (for example a quick test script) in a temporary directory outside "
        "this project, not in the workspace."
    ),
    "trig-lsp-outside": (
        "Also write a copy of the fixed greeter module to `/tmp/obench-shared/greeter_copy.py` "
        "(outside this project)."
    ),
}


def _files(root: Path) -> dict[str, bytes]:
    found = {}
    for path in root.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts:
            found[path.relative_to(root).as_posix()] = path.read_bytes()
    return found


class TriggerTaskTests(unittest.TestCase):
    def test_copies_keep_the_checker_and_prefix_the_instruction(self):
        for name, base in COPIES.items():
            with self.subTest(task=name):
                original = _files(TASKS / base)
                copied = _files(TASKS / name)
                for rel, body in original.items():
                    if rel in {"instruction.md", "PROVENANCE.md"}:
                        continue
                    self.assertEqual(copied[rel], body, rel)
                prefix = PREFIXES[name]
                text = copied["instruction.md"].decode("utf-8")
                self.assertTrue(text.startswith(prefix + "\n\n"), text[:120])
                self.assertEqual(text[len(prefix) + 2:], original["instruction.md"].decode("utf-8"))
                self.assertIn(base, copied["PROVENANCE.md"].decode("utf-8"))

    def test_task_map_names_the_triggerable_rows(self):
        mapping = load_task_map(TASK_MAP)
        self.assertEqual(len(mapping), 34)
        expected = {
            "623": "make-it-run",
            "3115": "trig-list",
            "4204": "trig-subagent-resume",
            "5066": "trig-bash-limits",
            "5131": "trig-bash-limits",
            "5140": "trig-workdir",
            "11731": "make-it-run",
            "12214": "trig-subagent-resume",
            "13090": "trig-read-edge",
            "13198": "trig-read-edge",
            "13269": "trig-grep-trunc",
            "17053": "make-it-run",
            "21070": "make-it-run",
            "22390": "trig-bash-limits",
            "2334": "trig-lsp-ts",
            "2367": "trig-list-noise",
            "24974": "trig-prompt-order",
            "25226": "trig-tmpdir",
            "25431": "trig-read-edge",
            "26821": "trig-todo-task",
            "3052": "trig-image-read",
            "4838": "taskflow",
            "6524": "make-it-run",
            "17098": "trig-skills",
            "19058": "trig-lsp-outside",
            "913": "trig-list-noise",
            "984": "make-ci-green",
            "1248": "trig-plan-subagent",
            "13331": "trig-webfetch-image",
        }
        triggerable = {pr: row.tasks for pr, row in mapping.items() if row.status == "triggerable"}
        self.assertEqual(triggerable, {pr: (task,) for pr, task in expected.items()})
        for task in set(expected.values()):
            self.assertTrue((TASKS / task / "checker.sh").is_file(), task)
        self.assertEqual(mapping["4838"].options.context, 72000)
        self.assertEqual(mapping["2334"].options.lsp, ("typescript",))
        self.assertEqual(mapping["6524"].options.lsp, ("pyright",))
        self.assertEqual(mapping["19058"].options.lsp, ("pyright",))
        self.assertTrue(mapping["24974"].options.global_agents)
        self.assertEqual(mapping["25226"].options.permissions, "workspace")
        self.assertEqual(mapping["22390"].options.as_text(), "")
        self.assertEqual(mapping["1248"].status, "triggerable")
        self.assertEqual(mapping["1248"].tasks, ("trig-plan-subagent",))
        self.assertEqual(mapping["1248"].options.mode, "plan")
        self.assertEqual(mapping["913"].tasks, ("trig-list-noise",))
        self.assertEqual(mapping["984"].tasks, ("make-ci-green",))
        self.assertEqual(mapping["984"].options.mode, "build")
        self.assertEqual(mapping["984"].options.disable_tools, ("bash", "write"))
        self.assertEqual(
            mapping["984"].options.as_text(),
            "mode=build disable-tools=bash,write",
        )
        self.assertEqual(mapping["3052"].options.modalities, "image")
        self.assertEqual(mapping["13331"].options.webfetch, "local")
        held = {
            "3369": ("make-it-run", "incompatible"),
            "3418": ("trig-dup-edit", "incompatible"),
            "5527": ("make-it-run", "needs fixture"),
            "23771": ("trig-lsp-csharp", "needs fixture"),
            "18140": ("make-it-run", "untriggerable"),
        }
        for pr, (task, status) in held.items():
            self.assertEqual(mapping[pr].tasks, (task,), pr)
            self.assertEqual(mapping[pr].status, status, pr)
        self.assertEqual(mapping["3369"].options.fault, "http-529")
        self.assertEqual(mapping["5527"].options.fault, "sse-server-error")
        self.assertEqual(mapping["23771"].options.lsp, ("dotnet",))
        self.assertEqual(len(mapping), 34)
        for pr, row in mapping.items():
            self.assertTrue(row.tasks, pr)
            self.assertTrue(row.status, pr)

    def test_skill_and_prompt_order_keep_the_instruction_and_add_files(self):
        original = (TASKS / "make-it-run" / "instruction.md").read_bytes()
        for name in ("trig-skills", "trig-prompt-order"):
            with self.subTest(task=name):
                text = (TASKS / name / "instruction.md").read_bytes()
                self.assertEqual(text, original)
                skill = TASKS / name / "workspace" / ".claude" / "skills" / "python-run-check" / "SKILL.md"
                body = skill.read_text(encoding="utf-8")
                self.assertIn(
                    "Use when asked to make a Python program run; lists the exact verification command",
                    body,
                )
        notes = (TASKS / "trig-skills" / "workspace" / ".claude" / "skills" / "notes" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Use when writing a short note that is not the program itself", notes)
        agents = (TASKS / "trig-prompt-order" / "workspace" / "AGENTS.md").read_text(encoding="utf-8")
        self.assertEqual(agents, "Prefix every final answer with PROJECT-RULE.\n")
        listed = (TASKS / "trig-list-noise" / "instruction.md").read_text(encoding="utf-8")
        self.assertTrue(listed.startswith(
            "Start by listing the project with the list tool, then fix the failing test in tests/test_app.py."
        ))
        self.assertTrue((TASKS / "trig-list-noise" / "workspace" / ".ignore").is_file())
        self.assertTrue((TASKS / "trig-image-read" / "workspace" / "spec.png").is_file())
        self.assertIn(
            "node node_modules/typescript/bin/tsc --noEmit",
            (TASKS / "trig-lsp-ts" / "instruction.md").read_text(encoding="utf-8"),
        )
        self.assertIn("8417", (TASKS / "trig-lsp-ts" / "workspace" / "src" / "index.ts").read_text(encoding="utf-8"))

    def test_remaining_trigger_workspaces_match_the_brief(self):
        dup = (TASKS / "trig-dup-edit" / "instruction.md").read_text(encoding="utf-8")
        self.assertTrue(dup.startswith(
            "In fetch_remote() only, change retries to 5. Use a single edit call whose oldString is exactly `retries = 3`"
        ))
        limits = (TASKS / "trig-dup-edit" / "workspace" / "limits.py").read_text(encoding="utf-8")
        self.assertEqual(limits.count("retries = 3"), 2)
        self.assertEqual(limits.count("backoff = 2"), 2)
        self.assertIn(
            "retries = 5",
            (TASKS / "trig-dup-edit" / "solution" / "limits.py").read_text(encoding="utf-8"),
        )
        fetched = (TASKS / "trig-webfetch-image" / "instruction.md").read_text(encoding="utf-8")
        self.assertIn("__OBENCH_WEBFETCH_URL__", fetched)
        self.assertIn("dominant colour", fetched)
        self.assertEqual(
            (TASKS / "trig-webfetch-image" / "solution" / "answer.txt").read_text(encoding="utf-8").strip(),
            "red",
        )
        self.assertEqual(
            (TASKS / "trig-lsp-csharp" / "instruction.md").read_text(encoding="utf-8").strip(),
            "Fix the compile error in Program.cs.",
        )
        broken = (TASKS / "trig-lsp-csharp" / "workspace" / "Program.cs").read_text(encoding="utf-8")
        self.assertIn("missingPort", broken)
        fixed = (TASKS / "trig-lsp-csharp" / "solution" / "Program.cs").read_text(encoding="utf-8")
        self.assertNotIn("missingPort", fixed)
        self.assertIn("8417", fixed)
        for name in ("trig-dup-edit", "trig-webfetch-image", "trig-lsp-csharp"):
            self.assertTrue((TASKS / name / "checker.sh").is_file(), name)


class EvidenceGrepTests(unittest.TestCase):
    def test_real_patterns_match_both_storage_layouts(self):
        patterns = load_patterns(PATTERNS)
        self.assertEqual(len(patterns), 34)
        out = Path(tempfile.mkdtemp())

        def cell(pr, side, task, trial, body):
            path = out / pr / "cells" / side / task / f"{trial}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "task": task, "trial": trial, "run_id": f"{pr}:{side}:{task}:{trial}",
            }), encoding="utf-8")
            return path

        # Transcript hit for the bash-metadata pattern (PR 5066).
        cell("5066", "with", "trig-bash-limits", 1, None)
        transcript = out / "5066" / "transcripts" / "with" / "5066_with_trig-bash-limits_1.txt"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text(
            "# transcript\n# harness=opencode model=claude-opus-5-5 "
            "task=trig-bash-limits trial=1 ts=t\n\n"
            '{"type":"tool_use","part":{"tool":"bash","state":{"output":"<bash_metadata>\\ntruncated"}}}\n',
            encoding="utf-8",
        )

        # Same PR, files present, pattern absent.
        cell("5066", "without", "trig-bash-limits", 1, None)
        parent_txt = out / "5066" / "transcripts" / "without" / "5066_without_trig-bash-limits_1.txt"
        parent_txt.parent.mkdir(parents=True, exist_ok=True)
        parent_txt.write_text(
            "task=trig-bash-limits trial=1\n(Output was truncated due to length limit)\n",
            encoding="utf-8",
        )

        # Old project/<id>/storage layout. The list pattern allows the optional space.
        cell("3115", "without", "trig-list", 1, None)
        old = (
            out / "3115" / "transcripts" / "without" / "trig-list" / "1"
            / "project" / "proj123" / "storage" / "part.json"
        )
        old.parent.mkdir(parents=True, exist_ok=True)
        old.write_text('{\n  "tool": "list"\n}\n', encoding="utf-8")

        # Modern storage layout, escaped newline after <content> (PR 21070).
        cell("21070", "with", "make-it-run", 1, None)
        modern = out / "21070" / "transcripts" / "with" / "make-it-run" / "1" / "storage" / "read.json"
        modern.parent.mkdir(parents=True, exist_ok=True)
        modern.write_text('{"output":"<content>\\n1: print(\\"hi\\") "}\n', encoding="utf-8")

        # Backreference: offset 3 must be followed by content starting at line 3 (PR 13198).
        cell("13198", "with", "trig-read-edge", 1, None)
        hit = out / "13198" / "transcripts" / "with" / "trig-read-edge" / "1" / "storage" / "read.json"
        hit.parent.mkdir(parents=True, exist_ok=True)
        hit.write_text(
            '{"tool":"read","state":{"status":"completed","input":{"offset":3},'
            '"output":"<path>catalog/books.py</path>\\n<type>file</type>\\n<content>3: def load"}}\n',
            encoding="utf-8",
        )
        cell("13198", "without", "trig-read-edge", 1, None)
        miss = out / "13198" / "transcripts" / "without" / "trig-read-edge" / "1" / "log" / "opencode.log"
        miss.parent.mkdir(parents=True, exist_ok=True)
        miss.write_text(
            '{"tool":"read","state":{"status":"completed","input":{"offset":3},'
            '"output":"<path>catalog/books.py</path>\\n<type>file</type>\\n<content>4: def load"}}\n',
            encoding="utf-8",
        )

        # No transcript and no copied storage.
        cell("623", "with", "make-it-run", 1, None)

        payload = annotate(out, patterns)
        sides = payload["prs"]

        def status(pr, side, trial=1, task=None):
            row = json.loads((out / pr / "cells" / side / task / f"{trial}.json").read_text(encoding="utf-8"))
            return row["exercised"]

        self.assertEqual(status("5066", "with", task="trig-bash-limits"), EXERCISED)
        self.assertEqual(status("5066", "without", task="trig-bash-limits"), NOT_EXERCISED)
        self.assertEqual(status("3115", "without", task="trig-list"), EXERCISED)
        self.assertEqual(status("21070", "with", task="make-it-run"), EXERCISED)
        self.assertEqual(status("13198", "with", task="trig-read-edge"), EXERCISED)
        self.assertEqual(status("13198", "without", task="trig-read-edge"), NOT_EXERCISED)
        self.assertEqual(status("623", "with", task="make-it-run"), UNDETERMINABLE)
        self.assertEqual(sides["5066"]["sides"]["with"][EXERCISED], 1)
        self.assertEqual(sides["5066"]["sides"]["without"][NOT_EXERCISED], 1)
        self.assertEqual(sides["623"]["sides"]["with"][UNDETERMINABLE], 1)
        self.assertTrue((out / "evidence-summary.json").is_file())

    def test_list_noise_pattern_reads_ignored_dirs_in_the_listing(self):
        pattern = load_patterns(PATTERNS)["913"].compiled
        present = (
            '{"tool":"list","state":{"output":"'
            'src/app.py\\nvendor/leftpad.py\\nvenv/pyvenv.cfg\\n'
            'coverage/index.txt\\nlogs/app.log\\ntmp/out.txt"}}'
        )
        absent = '{"tool":"list","state":{"output":"src/app.py\\ntests/test_app.py\\n"}}'
        bare = '{\n  "tool": "list"\n}\n'
        text_present = "|  List  \nvendor/leftpad.py\nsrc/app.py\n"
        text_absent = "|  List  \nsrc/app.py\ntests/test_app.py\n"
        self.assertIsNotNone(pattern.search(present))
        self.assertIsNotNone(pattern.search(absent))
        self.assertIsNone(pattern.search(bare))
        self.assertIsNotNone(pattern.search(text_present))
        self.assertIsNotNone(pattern.search(text_absent))
        # 2367 still treats any list call as exercised. 913 does not.
        list_only = load_patterns(PATTERNS)["2367"].compiled
        self.assertIsNotNone(list_only.search(bare))
        noise = TASKS / "trig-list-noise" / "workspace"
        for name in ("vendor", "venv", "coverage", "logs", "tmp"):
            files = [path for path in (noise / name).iterdir() if path.is_file()]
            self.assertGreaterEqual(len(files), 2, name)

    def test_cli_defaults_to_the_committed_pattern_file(self):
        fixtures = ROOT / "thesis" / "ab" / "fixtures"
        self.assertEqual(DEFAULT_PATTERNS, fixtures / "trigger-evidence.csv")
        self.assertEqual(PATTERNS, DEFAULT_PATTERNS)
        for name in ("trigger-tasks-34.md", "trigger-tasks-34.csv", "trigger-evidence.csv"):
            self.assertTrue((fixtures / name).is_file(), name)
        self.assertEqual(len(load_patterns(DEFAULT_PATTERNS)), 34)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.assertEqual(main([str(out)]), 0)
            summary = json.loads((out / "evidence-summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary, {"prs": {}})

    def test_984_is_exercised_only_with_edit_and_no_bash_or_write(self):
        pattern = load_patterns(PATTERNS)["984"].compiled
        edit = '{\n  "tool": "edit"\n}\n'
        bash = '{\n  "tool": "bash"\n}\n'
        write = '{"tool":"write"}'
        text_ui = "| Edit  catalog/books.py\n"
        self.assertEqual(classify_edit_only([], pattern), (UNDETERMINABLE, 0, 0))

        out = Path(tempfile.mkdtemp())

        def plant(side, body):
            cell = out / "984" / "cells" / side / "make-ci-green" / "1.json"
            cell.parent.mkdir(parents=True, exist_ok=True)
            cell.write_text(json.dumps({
                "task": "make-ci-green", "trial": 1, "run_id": f"984:{side}",
            }), encoding="utf-8")
            evidence = out / "984" / "transcripts" / side / "make-ci-green" / "1" / "part.json"
            evidence.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_text(body, encoding="utf-8")

        plant("with", edit + edit)
        plant("without", edit + bash)
        plant("aa-1", write + edit)
        plant("aa-2", text_ui)
        payload = annotate(out, load_patterns(PATTERNS))

        def row(side):
            path = out / "984" / "cells" / side / "make-ci-green" / "1.json"
            return json.loads(path.read_text(encoding="utf-8"))

        exercised = row("with")
        self.assertEqual(exercised["exercised"], EXERCISED)
        self.assertEqual(exercised["edit_calls"], 2)
        self.assertEqual(exercised["bash_write_calls"], 0)
        denied = row("without")
        self.assertEqual(denied["exercised"], NOT_EXERCISED)
        self.assertEqual(denied["edit_calls"], 1)
        self.assertEqual(denied["bash_write_calls"], 1)
        self.assertEqual(row("aa-1")["exercised"], NOT_EXERCISED)
        self.assertEqual(row("aa-1")["bash_write_calls"], 1)
        text = row("aa-2")
        self.assertEqual(text["exercised"], EXERCISED)
        self.assertEqual(text["edit_calls"], 1)
        self.assertEqual(payload["prs"]["984"]["sides"]["with"][EXERCISED], 1)
        self.assertEqual(payload["prs"]["984"]["sides"]["without"][NOT_EXERCISED], 1)


if __name__ == "__main__":
    unittest.main()
