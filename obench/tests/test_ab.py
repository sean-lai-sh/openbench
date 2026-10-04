#!/usr/bin/env python3
"""PR list parsing, A/B scheduling, and the summary table."""

import csv
import json
import os
import stat
import tempfile
import textwrap
import unittest
from pathlib import Path

from thesis.ab.build_opencode import build_plan
from thesis.ab.compat import Assessment
from thesis.ab.durable import publish_text
from thesis.ab.prs import PrListError, parse_prs, select_prs
from thesis.ab.run_ab import cell_file, drive, over_budget, read_cell
from thesis.ab.summarize import bootstrap_ci, pr_record, render_markdown, row_cost

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "thesis" / "ab" / "fixtures" / "opencode-harness-prs.csv"
SHA_A = "a" * 40
SHA_B = "b" * 40
PILOT = ["22390,24974,23771,4838,12214,18140"]


def _csv(rows, header):
    tmp = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8")
    writer = csv.DictWriter(tmp, fieldnames=header)
    writer.writeheader()
    writer.writerows(rows)
    tmp.close()
    return Path(tmp.name)


class TestFixture(unittest.TestCase):
    def test_real_list_parses_34_rows_and_trusts_23771(self):
        rows = parse_prs(FIXTURE)
        self.assertEqual(len(rows), 34)
        item = next(row for row in rows if row.pr == "23771")
        self.assertEqual(item.with_sha, "e383df4b17eecd6e6718e43c17438aa2eb818ee9")
        self.assertEqual(item.without_sha, "58db41b4b9fac2bfcf1f935cc114b3e4a069eade")
        self.assertEqual(item.category, "lsp/diagnostics")
        self.assertIn("textDocument/diagnostic", item.harness_change)
        oldest = min(rows, key=lambda row: row.merged)
        self.assertEqual(oldest.pr, "623")
        self.assertEqual(oldest.without_sha, "b99565959bb7a094e339802076d6ad6fd7d7f83c")
        chosen = select_prs(rows, PILOT)
        self.assertEqual(
            {row.pr for row in chosen},
            {"22390", "24974", "23771", "4838", "12214", "18140"},
        )

    def test_header_order_and_extra_column(self):
        path = _csv(
            [{
                "Parent/base SHA": SHA_A,
                "PR": "7",
                "Merge commit SHA": SHA_B,
                "Notes": "ignored",
                "Title": "Order",
                "Harness change": "Moves the skill block.",
            }],
            ["Notes", "Parent/base SHA", "Title", "PR", "Merge commit SHA", "Harness change"],
        )
        self.addCleanup(path.unlink)
        item = parse_prs(path)[0]
        self.assertEqual(item.pr, "7")
        self.assertEqual(item.without_sha, SHA_A)
        self.assertEqual(item.with_sha, SHA_B)
        self.assertEqual(item.harness_change, "Moves the skill block.")

    def test_fallback_csv_and_jsonl(self):
        path = _csv(
            [{"pr": "9", "before_sha": SHA_A, "after_sha": SHA_B, "title": "Fallback"}],
            ["pr", "before_sha", "after_sha", "title"],
        )
        self.addCleanup(path.unlink)
        item = parse_prs(path)[0]
        self.assertEqual(item.title, "Fallback")
        self.assertEqual(item.with_sha, SHA_B)
        jsonl = Path(tempfile.mkdtemp()) / "prs.jsonl"
        self.addCleanup(lambda: jsonl.unlink(missing_ok=True))
        jsonl.write_text(json.dumps({
            "pr": "11", "before_sha": SHA_A, "after_sha": SHA_B, "category": "tool",
        }) + "\n", encoding="utf-8")
        loaded = parse_prs(jsonl)[0]
        self.assertEqual(loaded.pr, "11")
        self.assertEqual(loaded.category, "tool")

    def test_duplicate_pr_and_short_sha_fail(self):
        dup = _csv(
            [
                {"pr": "1", "before_sha": SHA_A, "after_sha": SHA_B},
                {"pr": "1", "before_sha": SHA_A, "after_sha": SHA_B},
            ],
            ["pr", "before_sha", "after_sha"],
        )
        self.addCleanup(dup.unlink)
        with self.assertRaises(PrListError) as raised:
            parse_prs(dup)
        self.assertIn("duplicate PR 1", str(raised.exception))
        short = _csv(
            [{"pr": "2", "before_sha": "abc", "after_sha": SHA_B}],
            ["pr", "before_sha", "after_sha"],
        )
        self.addCleanup(short.unlink)
        with self.assertRaises(PrListError) as raised:
            parse_prs(short)
        self.assertIn("40-character SHA", str(raised.exception))


class TestSchedule(unittest.TestCase):
    def _prs(self):
        path = _csv(
            [{
                "PR": "1",
                "Title": "Title one",
                "Category": "tool",
                "Harness change": "Changes the bash timeout hint.",
                "Merge commit SHA": SHA_B,
                "Parent/base SHA": SHA_A,
            }],
            ["PR", "Title", "Category", "Harness change", "Merge commit SHA", "Parent/base SHA"],
        )
        self.addCleanup(path.unlink)
        return parse_prs(path)

    def test_dry_run_does_not_build(self):
        def build_fn(sha, cache, repo=""):
            raise AssertionError("build")

        plan, launched, stopped = drive(
            self._prs(), ("make-it-run",), 3, Path(tempfile.mkdtemp()),
            jobs=1, model="claude-opus-5-5", timeout_s=5, cache=Path("/tmp"),
            max_cost_usd=None, dry_run=True, tasks_dir=Path("/tmp"),
            build_fn=build_fn,
        )
        self.assertEqual(launched, 0)
        self.assertIsNone(stopped)
        self.assertIn(SHA_A, plan)
        self.assertIn("cells: 6", plan)

    def test_resume_skips_a_finished_cell(self):
        out = Path(tempfile.mkdtemp())
        existing = cell_file(out, "1", "without", "make-it-run", 1)
        publish_text(existing, json.dumps({"task": "make-it-run", "trial": 1, "score": 1}))
        calls = []

        def worker(spec):
            calls.append((spec["side"], spec["trial"]))
            publish_text(Path(spec["cell_path"]), json.dumps({
                "task": spec["task"], "trial": spec["trial"], "score": 0,
                "tokens_input_uncached": 0, "tokens_output": 0,
                "tokens_cache_read": 0, "tokens_cache_write": 0,
            }))

        def build_fn(sha, cache, repo=""):
            return Path("/tmp") / sha

        def assess_fn(binary):
            return Assessment("native", "listed", {}, False)

        _plan, launched, stopped = drive(
            self._prs(), ("make-it-run",), 1, out,
            jobs=1, model="claude-opus-5-5", timeout_s=5, cache=out,
            max_cost_usd=None, dry_run=False, tasks_dir=Path("/tmp"),
            build_fn=build_fn, assess_fn=assess_fn, worker=worker,
        )
        self.assertIsNone(stopped)
        self.assertEqual(launched, 1)
        self.assertEqual(calls, [("with", 1)])
        self.assertEqual(read_cell(existing)["score"], 1)

    def test_cost_cap_stops_before_the_next_cell(self):
        out = Path(tempfile.mkdtemp())
        calls = []

        def worker(spec):
            calls.append(spec["trial"])
            publish_text(Path(spec["cell_path"]), json.dumps({
                "tokens_input_uncached": 1_000_000,
                "tokens_output": 1_000_000,
                "tokens_cache_read": 1_000_000,
                "tokens_cache_write": 1_000_000,
                "task": spec["task"],
                "trial": spec["trial"],
            }))

        def build_fn(sha, cache, repo=""):
            return Path("/tmp") / sha

        def assess_fn(binary):
            return Assessment("configured", "supplied", {"provider": {}}, False)

        _plan, launched, stopped = drive(
            self._prs(), ("make-it-run",), 2, out,
            jobs=1, model="claude-opus-5-5", timeout_s=5, cache=out,
            max_cost_usd=10, dry_run=False, tasks_dir=Path("/tmp"),
            build_fn=build_fn, assess_fn=assess_fn, worker=worker,
        )
        self.assertEqual(calls, [1])
        self.assertEqual(launched, 1)
        self.assertEqual(stopped, "estimated cost $29.20 reached the $10.00 cap")

    def test_unmetered_row_stops_new_launches(self):
        out = Path(tempfile.mkdtemp())
        calls = []

        def worker(spec):
            calls.append(spec["trial"])
            publish_text(Path(spec["cell_path"]), json.dumps({"task": spec["task"], "trial": spec["trial"]}))

        def build_fn(sha, cache, repo=""):
            return Path("/tmp") / sha

        def assess_fn(binary):
            return Assessment("native", "listed", {}, False)

        _plan, launched, stopped = drive(
            self._prs(), ("make-it-run",), 2, out,
            jobs=1, model="claude-opus-5-5", timeout_s=5, cache=out,
            max_cost_usd=100, dry_run=False, tasks_dir=Path("/tmp"),
            build_fn=build_fn, assess_fn=assess_fn, worker=worker,
        )
        self.assertEqual(calls, [1])
        self.assertEqual(launched, 1)
        self.assertEqual(stopped, "unmetered tokens in a finished cell; not launching more cells")

    def test_incompatible_side_is_recorded_and_not_scored(self):
        out = Path(tempfile.mkdtemp())
        calls = []

        def worker(spec):
            calls.append(spec["side"])
            publish_text(Path(spec["cell_path"]), json.dumps({
                "task": spec["task"], "trial": spec["trial"], "score": 1, "success": True,
                "tokens_input_uncached": 1, "tokens_output": 1,
                "tokens_cache_read": 0, "tokens_cache_write": 0,
                "wall_time_s": 2, "failure_class": None,
            }))

        def build_fn(sha, cache, repo=""):
            return Path("/tmp") / sha

        def assess_fn(binary):
            if binary.endswith(SHA_A):
                return Assessment(
                    "incompatible",
                    "ProviderInitError while loading google-vertex-anthropic/claude-opus-5-5@default",
                    {},
                    False,
                )
            return Assessment("native", "listed", {}, False)

        drive(
            self._prs(), ("make-it-run",), 1, out,
            jobs=1, model="claude-opus-5-5", timeout_s=5, cache=out,
            max_cost_usd=None, dry_run=False, tasks_dir=Path("/tmp"),
            build_fn=build_fn, assess_fn=assess_fn, worker=worker,
        )
        self.assertEqual(calls, ["with"])
        sidecar = json.loads((out / "1" / "without.incompatible.json").read_text(encoding="utf-8"))
        self.assertEqual(sidecar["status"], "incompatible")
        self.assertEqual(sidecar["sha"], SHA_A)
        self.assertIn("ProviderInitError", sidecar["reason"])
        self.assertFalse((out / "1" / "cells" / "without").exists())
        record = pr_record(self._prs()[0], out)
        text = render_markdown([record])
        self.assertIn("Title: Title one", text)
        self.assertIn("Category: tool", text)
        self.assertIn("Harness change: Changes the bash timeout hint.", text)
        self.assertIn("without is incompatible: ProviderInitError", text)

    def test_row_cost_and_bootstrap_literals(self):
        self.assertEqual(row_cost({
            "tokens_input_uncached": 1_000_000,
            "tokens_output": 1_000_000,
            "tokens_cache_read": 1_000_000,
            "tokens_cache_write": 1_000_000,
        }), 29.2)
        self.assertEqual(bootstrap_ci([0.5, 0.5]), (0.5, 0.5))
        self.assertEqual(bootstrap_ci([0.0, 1.0], draws=1, seed=0), (1.0, 1.0))
        self.assertIsNone(over_budget(Path(tempfile.mkdtemp()), None))


class TestBuildPlan(unittest.TestCase):
    def test_publish_script_selects_host_compile(self):
        root = Path(tempfile.mkdtemp())
        script = root / "packages" / "opencode" / "script"
        script.mkdir(parents=True)
        (root / "package.json").write_text(
            json.dumps({"packageManager": "bun@1.2.14"}), encoding="utf-8")
        (script / "publish.ts").write_text("await $`bun build --compile`\n", encoding="utf-8")
        tui = root / "packages" / "tui"
        tui.mkdir()
        (tui / "go.mod").write_text("module tui\ngo 1.24.0\n", encoding="utf-8")
        plan = build_plan(root)
        self.assertEqual(plan["kind"], "compile")
        self.assertEqual(plan["bun"], "1.2.14")
        self.assertEqual(plan["go"], "1.24.0")

    def test_build_ts_forwards_single_and_skip_embed(self):
        root = Path(tempfile.mkdtemp())
        script = root / "packages" / "opencode" / "script"
        script.mkdir(parents=True)
        (root / "package.json").write_text(
            json.dumps({"packageManager": "bun@1.3.13"}), encoding="utf-8")
        (script / "build.ts").write_text(
            "flags --single and --skip-embed-web-ui\n", encoding="utf-8")
        plan = build_plan(root)
        self.assertEqual(plan["kind"], "build.ts")
        self.assertEqual(
            plan["args"],
            ["bun", "script/build.ts", "--single", "--skip-embed-web-ui"],
        )


class TestCellRun(unittest.TestCase):
    def test_execute_cell_records_a_checker_pass(self):
        from thesis.ab.run_ab import execute_cell
        root = Path(tempfile.mkdtemp())
        task = root / "tasks" / "demo"
        (task / "workspace").mkdir(parents=True)
        (task / "workspace" / "note.txt").write_text("hi", encoding="utf-8")
        (task / "instruction.md").write_text("say hi", encoding="utf-8")
        checker = task / "checker.sh"
        checker.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
        checker.chmod(checker.stat().st_mode | stat.S_IEXEC)
        binary = root / "opencode"
        binary.write_text(textwrap.dedent("""\
            #!/usr/bin/env python3
            import json, sys
            args = sys.argv[1:]
            if args == ["--version"]:
                print("cell-test")
                raise SystemExit(0)
            if args[:2] == ["run", "--help"]:
                print("--auto")
                print("-m, --model")
                print("--variant")
                print("--format")
                print("--dir")
                print("--title")
                raise SystemExit(0)
            print(json.dumps({"type": "step_finish", "part": {"tokens": {
                "input": 3, "output": 2, "reasoning": 1,
                "cache": {"read": 0, "write": 0}, "total": 6,
            }}}))
        """), encoding="utf-8")
        binary.chmod(0o755)
        dest = root / "cell.json"
        saved = os.environ.get("OBENCH_OPENCODE_BIN")
        try:
            execute_cell({
                "binary": str(binary),
                "config": {},
                "permission_config": False,
                "cell_path": str(dest),
                "tasks_dir": str(root / "tasks"),
                "adapters_dir": str(ROOT / "obench" / "adapters"),
                "model": "claude-opus-5-5",
                "task": "demo",
                "trial": 1,
                "timeout_s": 30,
            })
        finally:
            if saved is None:
                os.environ.pop("OBENCH_OPENCODE_BIN", None)
            else:
                os.environ["OBENCH_OPENCODE_BIN"] = saved
        row = json.loads(dest.read_text(encoding="utf-8"))
        self.assertTrue(row["success"])
        self.assertEqual(row["score"], 1.0)
        self.assertEqual(row["trial"], 1)
        self.assertEqual(row["task"], "demo")
        self.assertEqual(row["tokens_input_uncached"], 3)
        self.assertEqual(row["tokens_output"], 3)
        self.assertIn("cell-test", row["harness_version"])
        self.assertEqual(os.environ.get("OBENCH_OPENCODE_BIN"), saved)


if __name__ == "__main__":
    unittest.main()
