#!/usr/bin/env python3
"""PR list parsing, A/B scheduling, and the summary table."""

import csv
import io
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
from thesis.ab.prs import PrListError, PullRequest, parse_prs, select_prs
from thesis.ab.run_ab import cell_file, drive, over_budget, read_cell, unmetered_side, zero_metered
from thesis.ab.summarize import (
    bootstrap_ci,
    bootstrap_mean_diff,
    pr_record,
    render_csv,
    render_markdown,
    row_cost,
)

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

    def test_proxy_metered_score_is_not_infra(self):
        metered = {
            "score": 1.0,
            "success": True,
            "failure_class": None,
            "tokens": 142,
            "turns": None,
            "usage_raw": [{"input_tokens": 100, "output_tokens": 42}],
            "token_basis": "proxy_measured",
            "tokens_input_uncached": 100,
            "tokens_output": 42,
            "tokens_cache_read": 7,
            "tokens_cache_write": 3,
            "tokens_proxy_input_uncached": 100,
            "tokens_proxy_output": 42,
            "tokens_proxy_cache_read": 7,
            "tokens_proxy_cache_write": 3,
            "token_basis_proxy": "proxy_measured",
        }
        self.assertFalse(zero_metered(metered))
        self.assertIsNone(unmetered_side([metered, dict(metered)]))
        self.assertAlmostEqual(row_cost(metered), 0.0012564)
        bare = {
            "score": 1.0,
            "success": True,
            "tokens": None,
            "turns": None,
            "usage_raw": None,
            "token_basis": None,
            "tokens_proxy_input_uncached": 100,
            "tokens_proxy_output": 42,
            "tokens_proxy_cache_read": 7,
            "tokens_proxy_cache_write": 3,
            "token_basis_proxy": "proxy_measured",
        }
        self.assertFalse(zero_metered(bare))
        self.assertIsNone(unmetered_side([bare, dict(bare)]))
        self.assertAlmostEqual(row_cost(bare), 0.0012564)

    def test_cell_proxy_url_is_rewritten_for_that_cell_only(self):
        from thesis.ab.run_ab import bind_cell_proxy
        filled = bind_cell_proxy({
            "proxy": {
                "base_url": "http://127.0.0.1:9/v1",
                "model_ref": "anthropic/claude-opus-5-5",
            },
            "config": {
                "provider": {
                    "anthropic": {"options": {"baseURL": "http://127.0.0.1:9/v1"}},
                },
            },
        }, Path("/tmp/ledger"))
        base = filled["proxy"]["base_url"]
        self.assertTrue(base.startswith("http://127.0.0.1:9/c/"))
        self.assertTrue(base.endswith("/v1"))
        self.assertNotIn("/v1/c/", base)
        self.assertEqual(
            filled["config"]["provider"]["anthropic"]["options"]["baseURL"],
            base,
        )
        self.assertEqual(filled["proxy"]["ledger_dir"], "/tmp/ledger")
        self.assertEqual(len(filled["proxy"]["cell_id"]), 16)

    def test_july_beta_tree_installs_with_the_beta_alias(self):
        from thesis.ab.sdk_pin import install_alias_for_tree
        root = Path(tempfile.mkdtemp())
        provider = root / "packages" / "opencode" / "src" / "provider"
        provider.mkdir(parents=True)
        (provider / "provider.ts").write_text(
            'await BunProc.install("@aws-sdk/credential-providers")\n'
            'const mod = await import(await BunProc.install(pkg, "beta"))\n',
            encoding="utf-8",
        )
        self.assertEqual(install_alias_for_tree(root), "beta")
        self.assertEqual(install_alias_for_tree(Path(tempfile.mkdtemp())), "latest")

    def test_preflight_exit_before_meter_is_incompatible(self):
        from thesis.ab.run_ab import preflight_stop_reason
        reason = preflight_stop_reason({
            "completed": False,
            "error": "exit 1",
            "output_tail": "TypeError: createAnthropic is not a function",
            "tokens": None,
            "wall_time_s": 1.2,
        })
        self.assertEqual(
            reason,
            "preflight exited before any metered call: exit 1: TypeError: createAnthropic is not a function",
        )
        banner = preflight_stop_reason({
            "completed": False,
            "error": "exit 1",
            "output_tail": "\x1b[0m \u2588\u2580\u2580\u2588 \u2588\u2580\u2580\u2588 \x1b[1m> Reply with ok",
            "tokens": None,
        })
        self.assertEqual(
            banner,
            "preflight exited before any metered call: exit 1: > Reply with ok",
        )
        self.assertNotIn("\x1b", banner)
        self.assertIsNone(preflight_stop_reason({
            "completed": True,
            "error": None,
            "tokens": None,
        }))

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
        self.assertEqual(
            bootstrap_mean_diff([10.0, 30.0], [20.0, 40.0], draws=2, seed=0),
            (0.0, 10.0),
        )
        self.assertIsNone(over_budget(Path(tempfile.mkdtemp()), None))

    def test_per_task_deltas_and_headroom_pass_rate(self):
        out = Path(tempfile.mkdtemp())
        root = out / "9"
        root.mkdir()

        def row(task, score, success, wall, turns, uncached, failure=None):
            return {
                "task": task,
                "score": score,
                "success": success,
                "wall_time_s": wall,
                "turns": turns,
                "tokens_input_uncached": uncached,
                "tokens_output": 0,
                "tokens_cache_read": 0,
                "tokens_cache_write": 0,
                "failure_class": failure,
            }

        without = [
            row("ceiling", 1, True, 10, 2, 1_000_000),
            row("ceiling", 1, True, 10, 2, 1_000_000),
            row("open", 0, False, 30, 1, 1_000_000),
            row("open", 0, False, 30, 1, 1_000_000),
            row("open", 0, False, 9999, 99, 9_000_000, "infra"),
            row("solo", 0, False, 1, 1, 1),
        ]
        with_rows = [
            row("ceiling", 1, True, 20, 4, 2_000_000),
            row("ceiling", 1, True, 20, 4, 2_000_000),
            row("open", 1, True, 10, 3, 1_000_000),
            row("open", 1, True, 10, 3, 1_000_000),
        ]
        (root / "without.jsonl").write_text(
            "\n".join(json.dumps(item) for item in without) + "\n", encoding="utf-8")
        (root / "with.jsonl").write_text(
            "\n".join(json.dumps(item) for item in with_rows) + "\n", encoding="utf-8")
        pr = PullRequest(
            pr="9", title="Limit", merged="yes", with_sha=SHA_B, without_sha=SHA_A,
            nearest_release="", category="tool", files_changed="", key_paths="",
            one_line="", harness_change="Adds a limit.", bugfix_check="",
        )
        text = render_markdown([pr_record(pr, out)])
        per_task, _, headroom = text.partition("### Headroom")
        self.assertIn(
            "| ceiling | 10.000 | 10.000 to 10.000 | 2.000 | 2.000 to 2.000 "
            "| 1000000.0 | 1000000.0 to 1000000.0 | 4.000 | 4.000 to 4.000 |",
            per_task,
        )
        self.assertIn(
            "| open | -20.000 | -20.000 to -20.000 | 2.000 | 2.000 to 2.000 "
            "| 0.0 | 0.0 to 0.0 | 0.000 | 0.000 to 0.000 |",
            per_task,
        )
        self.assertNotIn("solo", text)
        self.assertNotIn("| ceiling |", headroom)
        self.assertIn(
            "| open | 0.000 | 1.000 | 0.000 | 1.000 |",
            headroom,
        )
        self.assertIn(
            "Pass-rate delta on headroom tasks (with minus without): 1.000 on 1 task. "
            "95% bootstrap interval: 1.000 to 1.000.",
            headroom,
        )
        self.assertIn("Score delta (with minus without): 0.500 on 2 paired tasks.", text)
        parsed = list(csv.DictReader(io.StringIO(render_csv([pr_record(pr, out)]))))
        self.assertEqual(parsed[0]["headroom_tasks"], "open")
        self.assertEqual(parsed[0]["headroom_n"], "1")
        self.assertEqual(parsed[0]["headroom_pass_delta"], "1.000")
        self.assertEqual(parsed[0]["headroom_pass_ci_low"], "1.000")
        self.assertEqual(parsed[0]["headroom_pass_ci_high"], "1.000")


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


def _lock(ai_version, ai_provider, anthropic_version, anthropic_provider):
    return {
        "packages": {
            "ai": [
                f"ai@{ai_version}",
                "",
                {"dependencies": {"@ai-sdk/provider": ai_provider}},
                "sha",
            ],
            "@ai-sdk/anthropic": [
                f"@ai-sdk/anthropic@{anthropic_version}",
                "",
                {"dependencies": {"@ai-sdk/provider": anthropic_provider}},
                "sha",
            ],
        },
    }


class TestBunAndSdkPin(unittest.TestCase):
    def test_checkout_bun_is_absolute_and_not_the_newest_install(self):
        from thesis.ab.run_ab import bun_for_checkout
        origin = Path.cwd()
        root = Path(tempfile.mkdtemp())
        os.chdir(root)
        self.addCleanup(os.chdir, origin)
        cache = Path("results/opencode-src")
        for version in ("1.2.14", "1.3.13"):
            dest = cache / "bun" / version / "bun"
            dest.parent.mkdir(parents=True)
            dest.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            dest.chmod(0o755)
        checkout = root / "checkout"
        checkout.mkdir()
        (checkout / "package.json").write_text(
            json.dumps({"packageManager": "bun@1.2.14+abcdef"}),
            encoding="utf-8",
        )
        chosen = bun_for_checkout(cache, checkout)
        other = Path(tempfile.mkdtemp())
        self.assertTrue(chosen.is_absolute())
        self.assertEqual(chosen.parent.name, "1.2.14")
        completed = __import__("subprocess").run(
            [str(chosen)], cwd=other, check=False,
        )
        self.assertEqual(completed.returncode, 0)

    def test_bun_version_file_wins_over_package_manager(self):
        from thesis.ab.run_ab import bun_for_checkout
        root = Path(tempfile.mkdtemp())
        cache = root / "cache"
        checkout = root / "checkout"
        checkout.mkdir()
        (checkout / ".bun-version").write_text("1.2.14\n", encoding="utf-8")
        (checkout / "package.json").write_text(
            json.dumps({"packageManager": "bun@1.3.13"}),
            encoding="utf-8",
        )
        chosen = bun_for_checkout(cache, checkout)
        self.assertTrue(chosen.is_absolute())
        self.assertEqual(chosen.parent.name, "1.2.14")

    def test_lockfile_pin_matches_the_ai_provider(self):
        from thesis.ab.sdk_pin import select_anthropic_pin
        registry = {
            "1.2.12": "1.1.3",
            "2.0.0-beta.10": "2.0.0-beta.1",
            "2.0.0-beta.11": "2.0.0-beta.1",
            "2.0.0": "2.0.0",
            "4.0.71": "4.0.21",
        }
        self.assertEqual(
            select_anthropic_pin(_lock("4.3.16", "1.1.3", "1.2.12", "1.1.3"), registry),
            "1.2.12",
        )
        self.assertEqual(
            select_anthropic_pin(_lock("5.0.8", "2.0.0", "2.0.0", "2.0.0"), registry),
            "2.0.0",
        )
        self.assertEqual(
            select_anthropic_pin(
                _lock("5.0.0-beta.7", "2.0.0-beta.1", "1.2.12", "1.1.3"),
                registry,
            ),
            "2.0.0-beta.11",
        )
        self.assertEqual(
            select_anthropic_pin(
                _lock("5.0.0-beta.15", "2.0.0-beta.1", "1.2.12", "1.1.3"),
                registry,
            ),
            "2.0.0-beta.11",
        )
        self.assertEqual(
            select_anthropic_pin(
                _lock("5.0.0-beta.21", "2.0.0-beta.1", "1.2.12", "1.1.3"),
                registry,
            ),
            "2.0.0-beta.11",
        )

    def test_jsonc_lockfile_on_disk_selects_the_same_pin(self):
        from thesis.ab.sdk_pin import anthropic_pin_for_tree
        root = Path(tempfile.mkdtemp())
        (root / "bun.lock").write_text(
            """
            {
              "packages": {
                "ai": ["ai@4.3.16", "", { "dependencies": { "@ai-sdk/provider": "1.1.3", }, }, "sha",],
                "@ai-sdk/anthropic": ["@ai-sdk/anthropic@1.2.12", "", { "dependencies": { "@ai-sdk/provider": "1.1.3", }, }, "sha",],
              },
            }
            """,
            encoding="utf-8",
        )
        self.assertEqual(anthropic_pin_for_tree(root, registry={}), "1.2.12")


class TestDistBinary(unittest.TestCase):
    def _tree(self, names):
        root = Path(tempfile.mkdtemp())
        pkg = root / "packages" / "opencode"
        paths = []
        for name in names:
            path = pkg / "dist" / name / "bin" / "opencode"
            path.parent.mkdir(parents=True)
            path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            path.chmod(0o755)
            paths.append(path)
        return root, paths

    def test_glibc_host_picks_the_non_baseline_binary(self):
        import platform
        from thesis.ab.build_opencode import _find_binary, select_dist_binary
        names = [
            "opencode-linux-x64",
            "opencode-linux-x64-baseline",
            "opencode-linux-x64-baseline-musl",
            "opencode-linux-x64-musl",
            "opencode-linux-arm64",
            "opencode-darwin-arm64",
        ]
        root, paths = self._tree(names)
        self.assertEqual(platform.libc_ver()[0], "glibc")
        self.assertEqual(_find_binary(root).parent.parent.name, "opencode-linux-x64")
        musl = select_dist_binary(paths, system="linux", machine="x64", libc="musl")
        self.assertEqual(musl.parent.parent.name, "opencode-linux-x64-musl")
        baseline_only = [
            path for path in paths
            if path.parent.parent.name in {
                "opencode-linux-x64-baseline",
                "opencode-linux-x64-musl",
            }
        ]
        baseline = select_dist_binary(baseline_only, system="linux", machine="x64", libc="glibc")
        self.assertEqual(baseline.parent.parent.name, "opencode-linux-x64-baseline")
        arm = select_dist_binary(paths, system="linux", machine="arm64", libc="glibc")
        self.assertEqual(arm.parent.parent.name, "opencode-linux-arm64")

    def _elf(self, path, interpreter):
        import struct
        interp = interpreter.encode() + b"\x00"
        phoff = 64
        phentsize = 56
        interp_off = phoff + phentsize
        header = struct.pack(
            "<16sHHIQQQIHHHHHH",
            b"\x7fELF" + bytes([2, 1, 1]) + b"\x00" * 9,
            2, 62, 1, 0, phoff, 0, 0, 64, phentsize, 1, 0, 0, 0,
        )
        program = struct.pack(
            "<IIQQQQQQ",
            3, 0, interp_off, interp_off, interp_off, len(interp), len(interp), 1,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(header + program + interp)
        path.chmod(0o755)

    def test_non_executable_dist_binary_is_marked_and_chosen(self):
        from thesis.ab.build_opencode import _find_binary
        root, paths = self._tree(["opencode-linux-x64", "opencode-linux-x64-musl"])
        glibc = next(path for path in paths if path.parent.parent.name == "opencode-linux-x64")
        glibc.chmod(0o644)
        wrapper = root / "packages" / "opencode" / "bin" / "opencode"
        wrapper.parent.mkdir(parents=True)
        wrapper.write_text("#!/usr/bin/env node\n", encoding="utf-8")
        wrapper.chmod(0o755)
        chosen = _find_binary(root)
        self.assertEqual(chosen, glibc)
        self.assertTrue(os.access(glibc, os.X_OK))

    def test_mislabeled_musl_binary_is_not_published(self):
        from thesis.ab.build_opencode import BuildError, _find_binary, can_exec, select_dist_binary
        root, paths = self._tree(["opencode-linux-x64-baseline"])
        musl = root / "packages" / "opencode" / "dist" / "opencode-linux-x64" / "bin" / "opencode"
        self._elf(musl, "/lib/ld-musl-x86_64.so.1")
        paths.append(musl)
        self.assertFalse(can_exec(musl))
        chosen = select_dist_binary(paths, system="linux", machine="x64", libc="glibc")
        self.assertEqual(chosen.parent.parent.name, "opencode-linux-x64-baseline")
        self.assertEqual(_find_binary(root), chosen)
        only_musl = root / "packages" / "opencode" / "dist" / "opencode-linux-x64-musl" / "bin" / "opencode"
        self._elf(only_musl, "/lib/ld-musl-x86_64.so.1")
        with self.assertRaises(BuildError):
            select_dist_binary([only_musl], system="linux", machine="x64", libc="glibc")

    def test_cached_musl_binary_is_rebuilt(self):
        from unittest.mock import patch
        from thesis.ab.build_opencode import binary, can_exec
        cache = Path(tempfile.mkdtemp())
        sha = "ab" * 20
        published = cache / "bin" / sha / "opencode"
        self._elf(published, "/lib/ld-musl-x86_64.so.1")
        good = Path(tempfile.mkdtemp()) / "opencode"
        good.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        good.chmod(0o755)

        def execute(_root, _plan, _cache):
            return good

        with patch("thesis.ab.build_opencode._ensure_mirror", return_value=cache / "mirror"), \
             patch("thesis.ab.build_opencode._ensure_worktree"), \
             patch("thesis.ab.build_opencode.build_plan", return_value={"kind": "build.ts"}), \
             patch("thesis.ab.build_opencode._execute_plan", side_effect=execute):
            result = binary(sha, cache)
        self.assertEqual(result, published.resolve())
        self.assertTrue(can_exec(result))
        self.assertTrue(result.read_text(encoding="utf-8").startswith("#!"))
        with patch("thesis.ab.build_opencode._execute_plan", side_effect=AssertionError("rebuilt")):
            again = binary(sha, cache)
        self.assertEqual(again, published.resolve())


class TestIncompatibleCells(unittest.TestCase):
    def _prs(self):
        return TestSchedule._prs(self)

    def test_stream_error_with_no_tokens_is_incompatible_and_not_scored(self):
        from thesis.ab.run_ab import provider_stream_failure
        out = Path(tempfile.mkdtemp())
        calls = []

        def worker(spec):
            calls.append((spec["side"], spec["trial"]))
            if spec["side"] == "without":
                body = {
                    "task": spec["task"],
                    "trial": spec["trial"],
                    "score": 0,
                    "success": False,
                    "completed": True,
                    "failure_class": "wrong_answer",
                    "error": "exit 1",
                    "output_tail": (
                        "ERROR service=session error=Error: "
                        "Unhandled chunk type: stream-start stream error"
                    ),
                    "tokens_input_uncached": None,
                    "tokens_output": None,
                    "tokens_cache_read": None,
                    "tokens_cache_write": None,
                }
            else:
                body = {
                    "task": spec["task"],
                    "trial": spec["trial"],
                    "score": 1,
                    "success": True,
                    "tokens_input_uncached": 4,
                    "tokens_output": 2,
                    "tokens_cache_read": 0,
                    "tokens_cache_write": 0,
                }
            publish_text(Path(spec["cell_path"]), json.dumps(body))

        def build_fn(sha, cache, repo=""):
            return Path("/tmp") / sha

        def assess_fn(binary):
            return Assessment("configured", "proxy", {}, False, proxy={
                "model_ref": "anthropic/claude-opus-5-5",
                "needs_sdk": False,
            })

        sample = {
            "error": "exit 1",
            "output_tail": "Unhandled chunk type: stream-start stream error",
            "tokens_output": 0,
        }
        self.assertIn("stream-start", provider_stream_failure(sample))
        self.assertIsNone(provider_stream_failure({**sample, "tokens_output": 12}))

        drive(
            self._prs(), ("make-it-run",), 2, out,
            jobs=1, model="claude-opus-5-5", timeout_s=5, cache=out,
            max_cost_usd=100, dry_run=False, tasks_dir=Path("/tmp"),
            build_fn=build_fn, assess_fn=assess_fn, worker=worker,
        )
        self.assertEqual(calls, [("without", 1), ("with", 1), ("with", 2)])
        sidecar = json.loads((out / "1" / "without.incompatible.json").read_text(encoding="utf-8"))
        self.assertEqual(sidecar["status"], "incompatible")
        self.assertIn("stream-start", sidecar["reason"])
        self.assertFalse((out / "1" / "with.incompatible.json").exists())
        record = pr_record(self._prs()[0], out)
        self.assertIn("without is incompatible", render_markdown([record]))
        self.assertEqual(record["without"]["n"], 0)
        self.assertEqual(record["with"]["n"], 2)
        stopped = over_budget(out, 100)
        self.assertIsNone(stopped)

    def test_preflight_failure_skips_the_side(self):
        out = Path(tempfile.mkdtemp())
        calls = []

        def worker(spec):
            calls.append(spec["side"])
            publish_text(Path(spec["cell_path"]), json.dumps({
                "task": spec["task"], "trial": spec["trial"], "score": 1, "success": True,
                "tokens_input_uncached": 1, "tokens_output": 1,
                "tokens_cache_read": 0, "tokens_cache_write": 0,
            }))

        def build_fn(sha, cache, repo=""):
            return Path("/tmp") / sha

        def assess_fn(binary):
            return Assessment("configured", "ok", {}, False)

        def preflight_fn(binary, state):
            if str(binary).endswith(SHA_A):
                return "preflight: Unhandled chunk type: stream-start"
            return None

        drive(
            self._prs(), ("make-it-run",), 1, out,
            jobs=1, model="claude-opus-5-5", timeout_s=5, cache=out,
            max_cost_usd=None, dry_run=False, tasks_dir=Path("/tmp"),
            build_fn=build_fn, assess_fn=assess_fn, worker=worker,
            preflight_fn=preflight_fn,
        )
        self.assertEqual(calls, ["with"])
        sidecar = json.loads((out / "1" / "without.incompatible.json").read_text(encoding="utf-8"))
        self.assertIn("preflight", sidecar["reason"])

    def test_infra_cells_do_not_trip_the_cost_guard(self):
        out = Path(tempfile.mkdtemp())
        calls = []

        def worker(spec):
            calls.append(spec["trial"])
            failure = "infra" if spec["trial"] == 1 else None
            body = {
                "task": spec["task"],
                "trial": spec["trial"],
                "score": 0 if failure else 1,
                "success": failure is None,
                "failure_class": failure,
            }
            if failure is None:
                body.update({
                    "tokens_input_uncached": 1,
                    "tokens_output": 1,
                    "tokens_cache_read": 0,
                    "tokens_cache_write": 0,
                })
            publish_text(Path(spec["cell_path"]), json.dumps(body))

        def build_fn(sha, cache, repo=""):
            return Path("/tmp") / sha

        def assess_fn(binary):
            return Assessment("native", "listed", {}, False)

        _plan, launched, stopped = drive(
            self._prs(), ("make-it-run",), 2, out,
            jobs=1, model="claude-opus-5-5", timeout_s=2400, cache=out,
            max_cost_usd=100, dry_run=False, tasks_dir=Path("/tmp"),
            build_fn=build_fn, assess_fn=assess_fn, worker=worker,
        )
        self.assertEqual(calls, [1, 2, 1, 2])
        self.assertEqual(launched, 4)
        self.assertIsNone(stopped)

    def test_cell_timeout_stays_under_fifteen_minutes(self):
        out = Path(tempfile.mkdtemp())
        seen = []

        def worker(spec):
            seen.append(spec["timeout_s"])
            publish_text(Path(spec["cell_path"]), json.dumps({
                "task": spec["task"], "trial": spec["trial"], "score": 1, "success": True,
                "tokens_input_uncached": 1, "tokens_output": 1,
                "tokens_cache_read": 0, "tokens_cache_write": 0,
            }))

        def build_fn(sha, cache, repo=""):
            return Path("/tmp") / sha

        def assess_fn(binary):
            return Assessment("native", "listed", {}, False)

        drive(
            self._prs(), ("make-it-run",), 1, out,
            jobs=1, model="claude-opus-5-5", timeout_s=2400, cache=out,
            max_cost_usd=None, dry_run=False, tasks_dir=Path("/tmp"),
            build_fn=build_fn, assess_fn=assess_fn, worker=worker,
        )
        self.assertTrue(seen)
        self.assertTrue(all(timeout < 900 for timeout in seen))
        self.assertTrue(all(timeout >= 60 for timeout in seen))

    def test_drive_passes_the_checkout_bun_and_sdk_pin(self):
        origin = Path.cwd()
        root = Path(tempfile.mkdtemp())
        os.chdir(root)
        self.addCleanup(os.chdir, origin)
        cache = Path("results/opencode-src")
        seen = []

        def worker(spec):
            seen.append(spec["proxy"])
            publish_text(Path(spec["cell_path"]), json.dumps({
                "task": spec["task"], "trial": spec["trial"], "score": 1, "success": True,
                "tokens_input_uncached": 1, "tokens_output": 1,
                "tokens_cache_read": 0, "tokens_cache_write": 0,
            }))

        def build_fn(sha, cache_path, repo=""):
            checkout = Path(cache_path) / "worktrees" / sha
            checkout.mkdir(parents=True, exist_ok=True)
            (checkout / "package.json").write_text(
                json.dumps({"packageManager": "bun@1.2.14"}),
                encoding="utf-8",
            )
            (checkout / "bun.lock").write_text(json.dumps(_lock(
                "4.3.16", "1.1.3", "1.2.12", "1.1.3",
            )), encoding="utf-8")
            dest = Path(cache_path) / "bun" / "1.3.13" / "bun"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("#!/bin/sh\n", encoding="utf-8")
            dest.chmod(0o755)
            wanted = Path(cache_path) / "bun" / "1.2.14" / "bun"
            wanted.parent.mkdir(parents=True, exist_ok=True)
            wanted.write_text("#!/bin/sh\n", encoding="utf-8")
            wanted.chmod(0o755)
            return Path(cache_path) / "bin" / sha

        def assess_fn(binary):
            return Assessment("configured", "proxy", {}, False, proxy={
                "model_ref": "anthropic/claude-opus-5-5",
                "needs_sdk": True,
                "api_key": "proxy",
                "base_url": "http://127.0.0.1:9/v1",
            })

        drive(
            self._prs(), ("make-it-run",), 1, root / "out",
            jobs=1, model="claude-opus-5-5", timeout_s=5, cache=cache,
            max_cost_usd=None, dry_run=False, tasks_dir=Path("/tmp"),
            build_fn=build_fn, assess_fn=assess_fn, worker=worker,
        )
        self.assertEqual(len(seen), 2)
        for proxy in seen:
            bun = Path(proxy["bun"])
            self.assertTrue(bun.is_absolute())
            self.assertEqual(bun.parent.name, "1.2.14")
            self.assertEqual(proxy["anthropic_sdk"], "1.2.12")

    def test_decimal_error_with_no_tokens_is_incompatible(self):
        from thesis.ab.run_ab import provider_stream_failure
        out = Path(tempfile.mkdtemp())
        calls = []

        def worker(spec):
            calls.append((spec["side"], spec["trial"]))
            if spec["side"] == "without":
                body = {
                    "task": spec["task"],
                    "trial": spec["trial"],
                    "score": 0,
                    "success": False,
                    "completed": True,
                    "failure_class": "wrong_answer",
                    "error": "exit 1",
                    "output_tail": "Error: [DecimalError] Invalid argument: [object Object]",
                    "tokens_input_uncached": None,
                    "tokens_output": None,
                    "tokens_cache_read": None,
                    "tokens_cache_write": None,
                }
            else:
                body = {
                    "task": spec["task"],
                    "trial": spec["trial"],
                    "score": 1,
                    "success": True,
                    "tokens_input_uncached": 4,
                    "tokens_output": 2,
                    "tokens_cache_read": 0,
                    "tokens_cache_write": 0,
                }
            publish_text(Path(spec["cell_path"]), json.dumps(body))

        def build_fn(sha, cache, repo=""):
            return Path("/tmp") / sha

        def assess_fn(binary):
            return Assessment("configured", "proxy", {}, False, proxy={"needs_sdk": False})

        sample = {
            "output_tail": "Error: [DecimalError] Invalid argument: [object Object]",
            "tokens_output": 0,
        }
        self.assertEqual(
            provider_stream_failure(sample),
            "provider stream error with no metered tokens: Error: [DecimalError] Invalid argument: [object Object]",
        )

        drive(
            self._prs(), ("make-it-run",), 2, out,
            jobs=1, model="claude-opus-5-5", timeout_s=5, cache=out,
            max_cost_usd=100, dry_run=False, tasks_dir=Path("/tmp"),
            build_fn=build_fn, assess_fn=assess_fn, worker=worker,
        )
        self.assertEqual(calls, [("without", 1), ("with", 1), ("with", 2)])
        sidecar = json.loads((out / "1" / "without.incompatible.json").read_text(encoding="utf-8"))
        self.assertEqual(sidecar["status"], "incompatible")
        self.assertIn("DecimalError", sidecar["reason"])
        record = pr_record(self._prs()[0], out)
        self.assertEqual(record["without"]["n"], 0)
        self.assertEqual(record["with"]["n"], 2)
        self.assertIsNone(over_budget(out, 100))

    def test_mostly_infra_side_is_flagged_and_not_scored(self):
        out = Path(tempfile.mkdtemp())
        calls = []

        def worker(spec):
            calls.append((spec["side"], spec["trial"]))
            publish_text(Path(spec["cell_path"]), json.dumps({
                "task": spec["task"],
                "trial": spec["trial"],
                "score": 0,
                "success": False,
                "failure_class": "infra",
                "error": "[Errno 2] No such file or directory",
                "tokens_input_uncached": None,
                "tokens_output": None,
                "tokens_cache_read": None,
                "tokens_cache_write": None,
            }))

        def build_fn(sha, cache, repo=""):
            return Path("/tmp") / sha

        def assess_fn(binary):
            return Assessment("native", "listed", {}, False)

        drive(
            self._prs(), ("make-it-run",), 3, out,
            jobs=1, model="claude-opus-5-5", timeout_s=5, cache=out,
            max_cost_usd=100, dry_run=False, tasks_dir=Path("/tmp"),
            build_fn=build_fn, assess_fn=assess_fn, worker=worker,
        )
        self.assertEqual(
            calls,
            [("without", 1), ("without", 2), ("with", 1), ("with", 2)],
        )
        sidecar = json.loads((out / "1" / "without.infra.json").read_text(encoding="utf-8"))
        self.assertEqual(sidecar["status"], "infra")
        record = pr_record(self._prs()[0], out)
        self.assertEqual(record["without"]["n"], 0)
        self.assertEqual(record["with"]["n"], 0)
        self.assertIn("without is infra", render_markdown([record]))
        self.assertIsNone(over_budget(out, 100))


class TestToolchainRecord(unittest.TestCase):
    def _prs(self):
        return TestSchedule._prs(self)

    def _checkout(self, cache, sha, bun, ai, anthropic):
        checkout = Path(cache) / "worktrees" / sha
        checkout.mkdir(parents=True, exist_ok=True)
        (checkout / "package.json").write_text(
            json.dumps({"packageManager": f"bun@{bun}"}),
            encoding="utf-8",
        )
        (checkout / "bun.lock").write_text(
            json.dumps(_lock(ai, "2.0.0", anthropic, "2.0.0")),
            encoding="utf-8",
        )
        return checkout

    def test_each_side_records_bun_ai_and_the_installed_sdk(self):
        from thesis.ab.run_ab import apply_toolchain
        out = Path(tempfile.mkdtemp())
        cache = out / "cache"
        seen = []

        def worker(spec):
            seen.append(spec["toolchain"])
            row = {
                "task": spec["task"],
                "trial": spec["trial"],
                "score": 1,
                "success": True,
                "tokens_input_uncached": 1,
                "tokens_output": 1,
                "tokens_cache_read": 0,
                "tokens_cache_write": 0,
            }
            apply_toolchain(row, spec["toolchain"], spec["toolchain"]["anthropic"])
            publish_text(Path(spec["cell_path"]), json.dumps(row))

        def build_fn(sha, cache_path, repo=""):
            if sha == SHA_A:
                self._checkout(cache_path, sha, "1.2.14", "4.3.16", "1.2.12")
            else:
                self._checkout(cache_path, sha, "1.2.19", "5.0.8", "2.0.0")
            return Path(cache_path) / "bin" / sha

        def assess_fn(binary):
            return Assessment("configured", "proxy", {}, False, proxy={"needs_sdk": True})

        drive(
            self._prs(), ("make-it-run",), 1, out,
            jobs=1, model="claude-opus-5-5", timeout_s=5, cache=cache,
            max_cost_usd=None, dry_run=False, tasks_dir=Path("/tmp"),
            build_fn=build_fn, assess_fn=assess_fn, worker=worker,
        )
        self.assertEqual(seen, [
            {"ai": "4.3.16", "anthropic": "1.2.12", "bun": "1.2.14"},
            {"ai": "5.0.8", "anthropic": "2.0.0", "bun": "1.2.19"},
        ])
        without = json.loads((out / "1" / "without.toolchain.json").read_text(encoding="utf-8"))
        with_side = json.loads((out / "1" / "with.toolchain.json").read_text(encoding="utf-8"))
        self.assertEqual(without, seen[0])
        self.assertEqual(with_side, seen[1])
        record = pr_record(self._prs()[0], out)
        self.assertEqual(record["toolchain"]["without"]["anthropic"], "1.2.12")
        self.assertEqual(record["toolchain"]["with"]["anthropic"], "2.0.0")
        self.assertTrue(record["sdk_changed"])
        text = render_markdown([record])
        self.assertIn("without toolchain: bun 1.2.14, ai 4.3.16, @ai-sdk/anthropic 1.2.12", text)
        self.assertIn("with toolchain: bun 1.2.19, ai 5.0.8, @ai-sdk/anthropic 2.0.0", text)
        self.assertIn("SDK changed: harness delta may be confounded", text)
        parsed = list(csv.DictReader(io.StringIO(render_csv([record]))))
        self.assertEqual(parsed[0]["sdk_changed"], "yes")

    def test_matching_sdk_versions_are_not_flagged(self):
        out = Path(tempfile.mkdtemp()) / "1"
        out.mkdir(parents=True)
        body = {"bun": "1.2.14", "ai": "5.0.8", "anthropic": "2.0.0"}
        (out / "without.toolchain.json").write_text(json.dumps(body), encoding="utf-8")
        (out / "with.toolchain.json").write_text(json.dumps(body), encoding="utf-8")
        row = {
            "task": "make-it-run", "trial": 1, "score": 1, "success": True,
            "tokens_input_uncached": 1, "tokens_output": 1,
            "tokens_cache_read": 0, "tokens_cache_write": 0,
            "toolchain": body,
        }
        (out / "without.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
        (out / "with.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
        pr = self._prs()[0]
        record = pr_record(pr, out.parent)
        self.assertFalse(record["sdk_changed"])
        self.assertNotIn("SDK changed: harness delta may be confounded", render_markdown([record]))
        self.assertIn("@ai-sdk/anthropic 2.0.0", render_markdown([record]))

    def test_installed_sdk_replaces_the_requested_pin(self):
        from thesis.ab.run_ab import apply_toolchain
        row = {}
        apply_toolchain(
            row,
            {"bun": "1.2.14", "ai": "5.0.8", "anthropic": "2.0.0"},
            "2.0.1",
        )
        self.assertEqual(row["toolchain"], {
            "bun": "1.2.14",
            "ai": "5.0.8",
            "anthropic": "2.0.1",
        })

    def test_a_later_cell_keeps_the_installed_sdk(self):
        out = Path(tempfile.mkdtemp())
        cache = out / "cache"
        pin = {"bun": "1.2.14", "ai": "5.0.8", "anthropic": "2.0.0"}

        def worker(spec):
            row = {
                "task": spec["task"],
                "trial": spec["trial"],
                "score": 1,
                "success": True,
                "tokens_input_uncached": 1,
                "tokens_output": 1,
                "tokens_cache_read": 0,
                "tokens_cache_write": 0,
            }
            if spec["trial"] == 1:
                from thesis.ab.run_ab import apply_toolchain
                apply_toolchain(row, spec["toolchain"], "2.0.1")
                publish_text(
                    Path(spec["toolchain_path"]),
                    json.dumps(row["toolchain"], sort_keys=True),
                )
            publish_text(Path(spec["cell_path"]), json.dumps(row))

        def build_fn(sha, cache_path, repo=""):
            self._checkout(cache_path, sha, "1.2.14", "5.0.8", "2.0.0")
            return Path(cache_path) / "bin" / sha

        def assess_fn(binary):
            return Assessment("configured", "proxy", {}, False, proxy={"needs_sdk": True})

        drive(
            self._prs(), ("make-it-run",), 2, out,
            jobs=1, model="claude-opus-5-5", timeout_s=5, cache=cache,
            max_cost_usd=None, dry_run=False, tasks_dir=Path("/tmp"),
            build_fn=build_fn, assess_fn=assess_fn, worker=worker,
        )
        for side in ("without", "with"):
            body = json.loads((out / "1" / f"{side}.toolchain.json").read_text(encoding="utf-8"))
            self.assertEqual(body["bun"], pin["bun"])
            self.assertEqual(body["ai"], pin["ai"])
            self.assertEqual(body["anthropic"], "2.0.1")

    def test_installed_sdk_survives_a_later_pin_write(self):
        from thesis.ab.run_ab import publish_side_toolchain, write_toolchain
        out = Path(tempfile.mkdtemp())
        pin = {"bun": "1.2.14", "ai": "5.0.8", "anthropic": "2.0.0"}
        path = out / "1" / "without.toolchain.json"
        write_toolchain(out, "1", "without", pin)
        publish_side_toolchain(path, pin, "2.0.1")
        write_toolchain(out, "1", "without", pin)
        body = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(body, {
            "ai": "5.0.8",
            "anthropic": "2.0.1",
            "bun": "1.2.14",
        })


if __name__ == "__main__":
    unittest.main()
