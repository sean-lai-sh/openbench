"""Stage 4 base agent (AC2): Pi and OpenCode configs.

Checks every swappable row's citation against the sheet, the vendored
assets, and one scripted episode per config. Stubbed model only.
"""
import csv
import json
import re
import tempfile
import unittest
from pathlib import Path

from thesis.base_agent import config as C
from thesis.base_agent import harness_opencode as OC
from thesis.base_agent.slots import swappable_rows
from obench.tests.test_stage4_base_agent import Scripted, agent_for, text, use

REPO = Path(__file__).resolve().parents[2]
SHEET = REPO / "prereg" / "harness-components-2026-10-24.csv"
HARNESSES = ("pi", "opencode")


def sheet_rows():
    with open(SHEET) as fh:
        return {i: r for i, r in enumerate(csv.DictReader(fh), 1)}


class Citations(unittest.TestCase):
    def test_every_swappable_row_cites_the_sheet_cell(self):
        sheet = sheet_rows()
        for h in HARNESSES:
            cfg = C.load_config(h)
            rows = {int(k): v for k, v in cfg["rows"].items()}
            self.assertEqual(set(rows), {r.row for r in swappable_rows()}, h)
            for n, cite in rows.items():
                with self.subTest(harness=h, row=n):
                    self.assertTrue(cite["value"])
                    self.assertEqual(cite["sheet"], sheet[n][h])
                    src = sheet[n][f"{h}_src"]
                    if src:
                        self.assertTrue(cite["source"].startswith(src), cite["source"])

    def test_pins(self):
        """Pi stays on the sheet's pin. OpenCode follows the build the #196
        cells ran (ba54cee5, Researcher ruling 2026-10-30), not the sheet's
        c10134729d."""
        brief = (REPO / "prereg" / "harness-components-2026-10-24.md").read_text()
        self.assertIn("d0aa218", brief)
        self.assertTrue(C.load_config("pi")["harness_pin"].startswith("d0aa218"))
        self.assertTrue(C.load_config("opencode")["harness_pin"].startswith("ba54cee5"))
        self.assertEqual(OC.PIN, C.load_config("opencode")["harness_pin"])
        notes = (REPO / "results" / "pi-vs-oc-180-1029").glob("*/opencode/claude-sonnet-5-5.json")
        for f in notes:
            self.assertEqual(json.loads(f.read_text())["sha"], OC.PIN)

    def test_row_4_source(self):
        for h in HARNESSES:
            self.assertEqual(C.load_config(h)["rows"]["4"]["source"], "derived; measured at AC3")


class Provenance(unittest.TestCase):
    """Review criteria 1 and 2: every module cites an open-source harness at
    the config's pin (or is original), and nothing is tuned on the hard pack."""

    HARD_PACK = ("dna-insert", "filter-js-from-html", "model-extraction-relu-logits", "polyglot-rust-c",
                 "regex-chess", "sam-cell-seg", "torch-pipeline-parallelism", "torch-tensor-parallelism",
                 "video-processing")

    def test_harness_modules_cite_the_config_pin(self):
        from thesis.base_agent import modules
        fixed = C.load_fixed()
        for h in HARNESSES:
            cfg = C.load_config(h)
            resolved = C.resolve(cfg, fixed, "parity")
            cited = [modules.SOURCES[f"{slot}:{spec['impl']}"] for slot, spec in resolved["modules"].items()]
            m2 = resolved["modules"]["M2"]["params"]
            cited += [modules.SOURCES[f"tool:{m2['family']}:{t}"] for t in m2["tools"]
                      if (m2["family"], t) in modules.TOOLS]
            for src in cited:
                with self.subTest(harness=h, source=src):
                    self.assertTrue(src == modules.ORIGINAL or f"@{cfg['harness_pin']}:" in src)

    def test_no_hard_pack_task_named_in_configs_or_modules(self):
        pkg = C.PKG
        files = list((pkg / "configs").glob("*.toml")) + list(pkg.glob("*.py")) + list((pkg / "assets").rglob("*.txt"))
        for f in files:
            body = f.read_text(encoding="utf-8")
            for task in self.HARD_PACK:
                self.assertNotIn(task, body, f"{f.name} names hard-pack task {task}")


class Assets(unittest.TestCase):
    def test_vendored_text_and_licences(self):
        self.assertEqual(len((OC.ASSETS / "anthropic.txt").read_bytes()), 8212)  # sheet: 8.2 KB
        for d in ("opencode", "pi"):
            lic = (OC.ASSETS.parent / d / "LICENSE").read_text()
            self.assertTrue(lic.startswith("MIT License"), d)

    def test_opencode_text_assets_are_upstream_files(self):
        self.assertTrue(OC.asset("anthropic.txt").startswith("You are OpenCode"))
        self.assertNotIn("Claude Code", OC.asset("anthropic.txt"))
        self.assertIn("title", OC.asset("title.txt").lower())


class Resolution(unittest.TestCase):
    def tools(self, h, arm):
        cfg = C.load_config(h)
        a = agent_for(h, Scripted([]), tempfile.gettempdir(), arm=arm, cfg=cfg)
        return [t.name for t in a.tools()]

    def test_tool_lists(self):
        self.assertEqual(self.tools("pi", "parity"), ["read", "bash", "edit", "write"])
        self.assertEqual(self.tools("pi", "swap"), ["read", "bash", "edit", "write"])
        oc = ["question", "bash", "read", "glob", "grep", "edit", "write", "task", "webfetch", "todowrite", "skill"]
        self.assertEqual(self.tools("opencode", "parity"), oc)
        self.assertEqual(self.tools("opencode", "swap"), [t for t in oc if t != "webfetch"])

    def test_versions_differ_per_config_and_arm(self):
        fixed = C.load_fixed()
        seen = set()
        for h in ("base",) + HARNESSES:
            for arm in C.ARMS:
                cfg = C.load_config(h)
                seen.add(C.version_record(cfg, fixed, C.resolve(cfg, fixed, arm))["base_agent_version"])
        self.assertEqual(len(seen), 6)


class PiEpisode(unittest.TestCase):
    def test_prompt_and_edits(self):
        with tempfile.TemporaryDirectory() as wd:
            Path(wd, "m.py").write_text("a = 1\nb = 2\nc = 3\n")
            client = Scripted([
                use("edit", {"path": "m.py", "edits": [{"oldText": "a = 1", "newText": "a = 10"},
                                                       {"oldText": "c = 3", "newText": "c = 30"}]}, 1),
                use("edit", {"path": "m.py", "edits": [{"oldText": "= ", "newText": "="}]}, 2),
                text("done"),
            ])
            res = agent_for("pi", client, wd, arm="parity").run()
            self.assertEqual(Path(wd, "m.py").read_text(), "a = 10\nb = 2\nc = 30\n")
            self.assertIn("matched 3 times", client.requests[2][1]["messages"][-1]["content"][0]["content"])
            role, req = client.requests[0]
            self.assertEqual([r for r, _ in client.requests], ["main"] * 3)  # no side calls
            system = req["system"][0]["text"]
            self.assertTrue(system.startswith("You are an expert coding assistant operating inside pi"))
            for tag in ("<tools>", "<rules>", "<docs>", "<cwd>"):
                self.assertIn(tag, system)
            self.assertIn("- Use bash for file operations like ls, rg, find", system)
            self.assertIn("cache_control", req["tools"][-1])
            self.assertEqual(res["version"]["harness"], "pi")


class OpenCodeEpisode(unittest.TestCase):
    def test_title_todo_task_and_edit(self):
        with tempfile.TemporaryDirectory() as wd:
            Path(wd, "m.py").write_text("x = 1\n")
            client = Scripted([
                text("Fix m.py"),  # title side call
                use("todowrite", {"todos": [{"content": "edit", "status": "in_progress", "priority": "high"}]}, 1),
                use("task", {"description": "look", "prompt": "find x", "subagent_type": "general"}, 2),
                use("read", {"filePath": "m.py"}, 3),  # subagent step
                text("x is in m.py"),  # subagent final
                use("edit", {"filePath": str(Path(wd, "m.py")), "oldString": "x = 1", "newString": "x = 2"}, 4),
                text("done"),
            ])
            res = agent_for("opencode", client, wd, arm="parity").run()
            self.assertEqual(Path(wd, "m.py").read_text(), "x = 2\n")
            roles = [r for r, _ in client.requests]
            self.assertEqual(roles, ["side:title", "main", "main", "side:subagent", "side:subagent", "main", "main"])
            main = client.requests[1][1]
            self.assertEqual(len(main["system"]), 1)
            self.assertTrue(main["system"][0]["text"].startswith("You are OpenCode"))
            self.assertNotIn("Claude Code", main["system"][0]["text"])
            self.assertIn("cache_control", main["system"][0])
            self.assertIn("The exact model ID is anthropic/claude-test", main["system"][0]["text"])
            self.assertNotIn("thinking", main)  # row 9 ruling: OpenCode thinking off
            self.assertEqual(client.requests[0][1]["model"], "claude-sonnet-5-5")  # #189 small_model pin
            self.assertIs(res["row"]["small_model_deviation"], True)
            self.assertEqual(res["row"]["small_model"], "anthropic/claude-sonnet-5-5")
            self.assertEqual(res["row"]["small_model_default"], "anthropic/claude-haiku-4-5-20251001")
            self.assertEqual(res["row"]["base_agent_version"], res["version"]["base_agent_version"])
            bash = next(t for t in main["tools"] if t["name"] == "bash")
            self.assertIn(f"All commands run in {wd} by default", bash["description"])
            self.assertNotIn("{{workdir}}", json.dumps(main["tools"]))
            sub_tools = [t["name"] for t in client.requests[3][1]["tools"]]
            self.assertNotIn("task", sub_tools)
            self.assertNotIn("todowrite", sub_tools)
            task_result = client.requests[5][1]["messages"][-1]["content"][0]["content"]
            self.assertIn("<task_result>\nx is in m.py\n</task_result>", task_result)
            self.assertEqual(res["tool_calls"], {"todowrite": 1, "task": 1, "edit": 1})
            self.assertIn("subagent", [e["event"] for e in res["events"]])

    def test_question_and_skill_fail_headless(self):
        with tempfile.TemporaryDirectory() as wd:
            client = Scripted([text("t"), use("question", {"questions": []}, 1), use("skill", {"name": "x"}, 2),
                               text("ok")])
            agent_for("opencode", client, wd, arm="parity").run()
            self.assertTrue(client.requests[2][1]["messages"][-1]["content"][0]["is_error"])
            self.assertTrue(client.requests[3][1]["messages"][-1]["content"][0]["is_error"])

    def test_shell_timeout_is_milliseconds(self):
        with tempfile.TemporaryDirectory() as wd:
            client = Scripted([text("t"), use("bash", {"command": "sleep 3", "timeout": 200}, 1), text("ok")])
            agent_for("opencode", client, wd, arm="parity").run()
            self.assertIn("timed out after 0.2 seconds", client.requests[2][1]["messages"][-1]["content"][0]["content"])


if __name__ == "__main__":
    unittest.main()
