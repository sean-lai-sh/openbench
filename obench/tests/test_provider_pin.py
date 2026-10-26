"""Provider pins are per build and side, and a miss aborts before the model request."""

import json
import multiprocessing
import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STOCK = "4643e13170ab625801bf1e50af788147c00879d3"
PR_3185_WITH = "b3fcc9a81dd39dc8b595b003d722b89c158cdfbc"
PR_3185_WITHOUT = "e8751d976e38d0cbfeef1bb05c6014f9591f3973"


def _task(root: Path) -> None:
    task = root / "tasks" / "demo"
    (task / "workspace").mkdir(parents=True)
    (task / "instruction.md").write_text("say hi", encoding="utf-8")
    checker = task / "checker.sh"
    checker.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    checker.chmod(checker.stat().st_mode | stat.S_IEXEC)


def _write_script(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


class ManifestTests(unittest.TestCase):
    def test_stock_and_3185_are_keyed_by_build_and_side(self):
        from thesis.ab.provider_pin import load_manifest, lookup_packages, pin_sha256

        stock_a = lookup_packages(STOCK, "aa-1")
        stock_b = lookup_packages(STOCK, "aa-2")
        self.assertEqual(stock_a, {"@ai-sdk/anthropic": "3.0.64"})
        self.assertEqual(stock_b, {"@ai-sdk/anthropic": "3.0.64"})
        self.assertEqual(lookup_packages(STOCK[:12], "aa-1"), stock_a)
        self.assertIsNone(lookup_packages(PR_3185_WITH, "without"))
        self.assertEqual(
            lookup_packages(PR_3185_WITH, "with"),
            {"@ai-sdk/anthropic": "2.0.0"},
        )
        without = lookup_packages(PR_3185_WITHOUT, "without")
        self.assertEqual(without, {"@ai-sdk/anthropic": "2.0.0"})
        self.assertNotEqual(pin_sha256(stock_a), pin_sha256(without))
        self.assertEqual(
            pin_sha256({"@ai-sdk/anthropic": "3.0.64", "other": "1"}),
            pin_sha256({"other": "1", "@ai-sdk/anthropic": "3.0.64"}),
        )
        data = load_manifest()
        for sha, sides in data["builds"].items():
            versions = set()
            self.assertGreaterEqual(len(sha), 40, sha)
            for side, entry in sides.items():
                packages = entry["packages"]
                self.assertIn("@ai-sdk/anthropic", packages)
                self.assertNotEqual(packages["@ai-sdk/anthropic"], "latest")
                versions.add(packages["@ai-sdk/anthropic"])
                self.assertNotIn("@opencode-ai/plugin", packages)
            self.assertEqual(len(versions), 1, sha)
        entry = data["builds"][PR_3185_WITHOUT]["without"]
        self.assertEqual(entry["evidence"], "f03-1-seed")
        self.assertEqual(data["builds"][STOCK]["aa-1"]["evidence"], "box-aa")

    def test_missing_worktree_still_uses_the_manifest(self):
        from thesis.ab.provider_pin import apply_provider_pin
        from thesis.ab.run_ab import _overlay_provider_pin

        proxy = apply_provider_pin({}, "/tmp/cache", STOCK, "aa-1", "26821")
        self.assertEqual(proxy["anthropic_sdk"], "3.0.64")
        self.assertEqual(proxy["provider_pins"]["@ai-sdk/anthropic"], "3.0.64")
        self.assertTrue(proxy["provider_pin_sha256"])
        self.assertTrue(str(proxy["pin_store"]).endswith("provider-pins"))
        state = {
            "ok": True,
            "proxy": {"model_ref": "anthropic/claude-opus-5-5"},
            "toolchain": {},
        }
        overlaid = _overlay_provider_pin(
            state, Path("/tmp/pins"), {"sha": STOCK, "side": "aa-2", "pr": "26821"},
        )
        self.assertEqual(overlaid["proxy"]["anthropic_sdk"], "3.0.64")
        self.assertEqual(overlaid["toolchain"]["anthropic"], "3.0.64")
        self.assertNotIn("anthropic_sdk", state["proxy"])

    def test_unknown_build_keeps_an_exact_lockfile_pin(self):
        from thesis.ab.provider_pin import apply_provider_pin

        proxy = apply_provider_pin(
            {"anthropic_sdk": "1.2.12"}, "/tmp/cache", "a" * 40, "with", "1",
        )
        self.assertEqual(proxy["anthropic_sdk"], "1.2.12")
        self.assertEqual(proxy["provider_pins"], {"@ai-sdk/anthropic": "1.2.12"})
        bare = apply_provider_pin({}, "/tmp/cache", "a" * 40, "with", "1")
        self.assertNotIn("provider_pins", bare)

    def test_drive_applies_the_manifest_when_the_worktree_is_missing(self):
        from thesis.ab.compat import Assessment
        from thesis.ab.durable import publish_text
        from thesis.ab.prs import PullRequest
        from thesis.ab.run_ab import drive

        out = Path(tempfile.mkdtemp())
        seen = []

        def worker(spec):
            seen.append((spec["side"], spec["proxy"].get("anthropic_sdk")))
            publish_text(Path(spec["cell_path"]), json.dumps({
                "task": spec["task"], "trial": spec["trial"], "score": 1, "success": True,
                "tokens_input_uncached": 1, "tokens_output": 1,
                "tokens_cache_read": 0, "tokens_cache_write": 0,
            }))

        def build_fn(sha, cache, repo=""):
            return Path("/tmp") / sha

        def assess_fn(binary):
            return Assessment("configured", "proxy", {}, False, proxy={
                "model_ref": "anthropic/claude-opus-5-5",
                "needs_sdk": False,
                "api_key": "proxy",
                "base_url": "http://127.0.0.1:9/v1",
            })

        pr = PullRequest(
            pr="26821", title="stock", merged="", with_sha="b" * 40, without_sha=STOCK,
            nearest_release="", category="", files_changed="", key_paths="",
            one_line="", harness_change="", bugfix_check="",
        )
        drive(
            [pr], ("make-it-run",), 1, out,
            jobs=1, model="claude-opus-5-5", timeout_s=5, cache=out / "cache",
            max_cost_usd=None, dry_run=False, tasks_dir=Path("/tmp"),
            build_fn=build_fn, assess_fn=assess_fn, worker=worker, aa=True,
        )
        self.assertEqual(sorted(seen), [("aa-1", "3.0.64"), ("aa-2", "3.0.64")])


class GuardTests(unittest.TestCase):
    def test_empty_cache_and_mismatch_are_infra_reasons(self):
        from thesis.ab.provider_pin import mismatch_reason, violation_in_text

        root = Path(tempfile.mkdtemp())
        packages = {"@ai-sdk/anthropic": "2.0.0"}
        self.assertEqual(mismatch_reason(root, packages), "provider_pin_mismatch: empty cache")
        module = root / "node_modules" / "@ai-sdk" / "anthropic" / "package.json"
        module.parent.mkdir(parents=True)
        module.write_text('{"version": "4.0.88"}', encoding="utf-8")
        reason = mismatch_reason(root, packages)
        self.assertIn("provider_pin_mismatch", reason)
        self.assertIn("4.0.88", reason)
        self.assertIn("2.0.0", reason)
        module.write_text('{"version": "2.0.0"}', encoding="utf-8")
        self.assertEqual(mismatch_reason(root, packages), "")
        self.assertEqual(
            violation_in_text("pkg=@ai-sdk/anthropic version=latest\n"),
            "provider_pin_mismatch: version=latest",
        )
        self.assertEqual(
            violation_in_text("bun add @ai-sdk/anthropic@latest"),
            "provider_pin_mismatch: version=latest",
        )
        self.assertEqual(
            violation_in_text(
                "No version matching '0.0.0--1710000000' for @opencode-ai/plugin"
            ),
            "",
        )

    def test_seed_refuses_latest_and_reuses_one_template(self):
        from thesis.ab.provider_pin import pin_sha256, seed_cell_cache

        root = Path(tempfile.mkdtemp())
        count = root / "count.txt"
        bun = root / "bun"
        _write_script(bun, textwrap.dedent("""\
            #!/usr/bin/env python3
            import os, pathlib, sys, time
            args = sys.argv[1:]
            dest = pathlib.Path(os.environ["BUN_COUNT"])
            with dest.open("a", encoding="utf-8") as fh:
                fh.write("add\\n")
            time.sleep(0.4)
            cwd = pathlib.Path(args[args.index("--cwd") + 1])
            for arg in args:
                if not arg.startswith("@ai-sdk/"):
                    continue
                name, version = arg.rsplit("@", 1)
                module = cwd / "node_modules" / name / "package.json"
                module.parent.mkdir(parents=True, exist_ok=True)
                module.write_text('{"name": "%s", "version": "%s"}' % (name, version), encoding="utf-8")
        """))
        env = os.environ.copy()
        env["BUN_COUNT"] = str(count)
        store = root / "provider-pins"
        refused = seed_cell_cache(
            root / "nope", store, {"@ai-sdk/anthropic": "latest"}, str(bun), env,
        )
        self.assertIn("refused", refused)
        self.assertFalse(count.exists())
        packages = {"@ai-sdk/anthropic": "2.0.0"}
        cells = [root / "cell-a", root / "cell-b"]
        ctx = multiprocessing.get_context("fork")
        procs = [
            ctx.Process(
                target=seed_cell_cache,
                args=(cell, store, packages, str(bun), env),
            )
            for cell in cells
        ]
        for proc in procs:
            proc.start()
        for proc in procs:
            proc.join(10)
            self.assertFalse(proc.is_alive())
            self.assertEqual(proc.exitcode, 0)
        self.assertEqual(count.read_text(encoding="utf-8").count("add\n"), 1)
        for cell in cells:
            installed = json.loads(
                (cell / "node_modules" / "@ai-sdk" / "anthropic" / "package.json").read_text(
                    encoding="utf-8",
                )
            )
            self.assertEqual(installed["version"], "2.0.0")
        template = store / pin_sha256(packages)
        self.assertTrue((template / "node_modules" / "@ai-sdk" / "anthropic" / "package.json").is_file())


class CellAbortTests(unittest.TestCase):
    def _proxy(self, root: Path, bun: Path) -> dict:
        from thesis.ab.provider_pin import pin_sha256

        packages = {"@ai-sdk/anthropic": "2.0.0"}
        return {
            "needs_sdk": True,
            "model_ref": "anthropic/claude-opus-5-5",
            "api_key": "proxy",
            "anthropic_sdk": "2.0.0",
            "cache_version": "9",
            "bun": str(bun),
            "provider_pins": packages,
            "provider_pin_sha256": pin_sha256(packages),
            "pin_store": str(root / "provider-pins"),
        }

    def _binary(self, path: Path, started: Path, request: Path, body: str) -> None:
        script = textwrap.dedent("""\
            #!/usr/bin/env python3
            import pathlib, sys, time
            args = sys.argv[1:]
            if args == ["--version"]:
                print("cell-test")
                raise SystemExit(0)
            if args[:2] == ["run", "--help"]:
                print("--auto")
                print("-m, --model")
                print("--format")
                print("--dir")
                print("--title")
                raise SystemExit(0)
            pathlib.Path(STARTED).write_text("started", encoding="utf-8")
            BODY
        """).replace("STARTED", repr(str(started))).replace("BODY", body)
        _write_script(path, script)

    def _run(self, root: Path, binary: Path, bun: Path, **extra) -> dict:
        from thesis.ab.run_ab import execute_cell

        _task(root)
        spec = {
            "binary": str(binary),
            "config": {},
            "permission_config": False,
            "proxy": self._proxy(root, bun),
            "cell_path": str(root / "cell.json"),
            "tasks_dir": str(root / "tasks"),
            "adapters_dir": str(ROOT / "obench" / "adapters"),
            "model": "claude-opus-5-5",
            "task": "demo",
            "trial": 1,
            "side": "with",
            "pr": "3185",
            "sha": PR_3185_WITH,
            "timeout_s": 20,
            "transcripts_dir": str(root / "transcripts"),
            "evidence_dir": str(root / "transcripts" / "with" / "demo" / "1"),
        }
        spec.update(extra)
        saved = os.environ.get("OBENCH_OPENCODE_BIN")
        try:
            execute_cell(spec)
        finally:
            if saved is None:
                os.environ.pop("OBENCH_OPENCODE_BIN", None)
            else:
                os.environ["OBENCH_OPENCODE_BIN"] = saved
        return json.loads((root / "cell.json").read_text(encoding="utf-8"))

    def test_empty_cache_aborts_before_the_model_request(self):
        root = Path(tempfile.mkdtemp())
        started = root / "started"
        bun = root / "bun"
        _write_script(bun, "#!/bin/sh\nexit 0\n")
        binary = root / "opencode"
        self._binary(binary, started, root / "request", "raise SystemExit(0)\n")
        row = self._run(root, binary, bun)
        self.assertFalse(started.exists())
        self.assertEqual(row["failure_class"], "infra")
        self.assertIn("provider_pin_mismatch", row["failure_reason"])
        self.assertIn("empty cache", row["failure_reason"])
        self.assertFalse(row["success"])
        self.assertTrue(row["provider_pin_sha256"])
        self.assertEqual(row["provider_versions"]["@ai-sdk/anthropic"], "missing")
        self.assertIsNone(row.get("checker_exit"))

    def test_version_latest_is_killed_before_the_request_file(self):
        root = Path(tempfile.mkdtemp())
        started = root / "started"
        request = root / "request"
        bun = root / "bun"
        _write_script(bun, textwrap.dedent("""\
            #!/usr/bin/env python3
            import pathlib, sys
            args = sys.argv[1:]
            cwd = pathlib.Path(args[args.index("--cwd") + 1])
            for arg in args:
                if arg.startswith("@ai-sdk/anthropic@"):
                    version = arg.rsplit("@", 1)[1]
                    module = cwd / "node_modules" / "@ai-sdk" / "anthropic" / "package.json"
                    module.parent.mkdir(parents=True, exist_ok=True)
                    module.write_text('{"version": "%s"}' % version, encoding="utf-8")
        """))
        binary = root / "opencode"
        self._binary(
            binary,
            started,
            request,
            textwrap.dedent("""\
                print("pkg=@ai-sdk/anthropic version=latest", flush=True)
                time.sleep(15)
                pathlib.Path(REQUEST).write_text("sent", encoding="utf-8")
            """).replace("REQUEST", repr(str(request))),
        )
        row = self._run(root, binary, bun, no_progress_s=30)
        self.assertTrue(started.exists())
        self.assertFalse(request.exists())
        self.assertEqual(row["failure_class"], "infra")
        self.assertIn("provider_pin_mismatch", row["failure_reason"])
        self.assertIn("version=latest", row["failure_reason"])
        self.assertFalse(row["success"])
        self.assertEqual(row["provider_versions"]["@ai-sdk/anthropic"], "2.0.0")


class RunnerCommitTests(unittest.TestCase):
    def test_explicit_commit_wins_over_a_missing_gitdir(self):
        from thesis.ab.run_ab import resolve_runner_commit

        root = Path(tempfile.mkdtemp()) / "repo"
        root.mkdir()
        (root / ".git").write_text("gitdir: /no/such/gitdir\n", encoding="utf-8")
        saved = os.environ.get("OBENCH_RUNNER_COMMIT")
        os.environ["OBENCH_RUNNER_COMMIT"] = "from-env"
        try:
            self.assertEqual(resolve_runner_commit(root=root), "from-env")
            os.environ.pop("OBENCH_RUNNER_COMMIT")
            self.assertIsNone(resolve_runner_commit(root=root))
            self.assertEqual(resolve_runner_commit("from-cli", root=root), "from-cli")
        finally:
            if saved is None:
                os.environ.pop("OBENCH_RUNNER_COMMIT", None)
            else:
                os.environ["OBENCH_RUNNER_COMMIT"] = saved

    def test_env_wins_and_gitfile_fallback_reads_the_gitdir(self):
        from thesis.ab.run_ab import resolve_runner_commit

        root = Path(tempfile.mkdtemp()) / "src"
        root.mkdir()
        subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
        (root / "f").write_text("a", encoding="utf-8")
        subprocess.run(["git", "add", "f"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-m", "t"], cwd=root, check=True, capture_output=True)
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        other = Path(tempfile.mkdtemp()) / "mount"
        other.mkdir()
        (other / ".git").write_text(f"gitdir: {root / '.git'}\n", encoding="utf-8")
        saved = os.environ.pop("OBENCH_RUNNER_COMMIT", None)
        try:
            self.assertEqual(resolve_runner_commit(root=other), sha)
            os.environ["OBENCH_RUNNER_COMMIT"] = "host-passed"
            self.assertEqual(resolve_runner_commit(root=other), "host-passed")
            self.assertEqual(resolve_runner_commit("cli", root=other), "cli")
        finally:
            if saved is None:
                os.environ.pop("OBENCH_RUNNER_COMMIT", None)
            else:
                os.environ["OBENCH_RUNNER_COMMIT"] = saved

    def test_backfill_fills_empty_commits_and_aborts_on_disagreement(self):
        from thesis.ab.backfill_runner_commit import BackfillError, backfill_runner_commit

        root = Path(tempfile.mkdtemp())
        log = root / "driver.log"
        log.write_text("runner=980e71b618\nrunner=980e71b618abcd\n", encoding="utf-8")
        cells = root / "cells"
        cells.mkdir()
        empty = cells / "1.json"
        empty.write_text(json.dumps({"task": "demo", "trial": 1, "runner_commit": None}), encoding="utf-8")
        kept = cells / "2.json"
        kept.write_text(
            json.dumps({"task": "demo", "trial": 2, "runner_commit": "already"}),
            encoding="utf-8",
        )
        sidecar = cells / "arm.json"
        sidecar.write_text(json.dumps({"sha": "abc"}), encoding="utf-8")
        self.assertEqual(backfill_runner_commit(log, cells), 1)
        self.assertEqual(json.loads(empty.read_text(encoding="utf-8"))["runner_commit"], "980e71b618abcd")
        self.assertEqual(json.loads(kept.read_text(encoding="utf-8"))["runner_commit"], "already")
        self.assertNotIn("runner_commit", json.loads(sidecar.read_text(encoding="utf-8")))
        bad = root / "bad.log"
        bad.write_text("runner=aaaaaaaa\nrunner=bbbbbbbb\n", encoding="utf-8")
        before = empty.read_text(encoding="utf-8")
        with self.assertRaises(BackfillError):
            backfill_runner_commit(bad, cells)
        self.assertEqual(empty.read_text(encoding="utf-8"), before)


class PrintTests(unittest.TestCase):
    def test_print_stock_pin(self):
        import io
        from contextlib import redirect_stdout

        from thesis.ab.print_provider_versions import main

        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main([STOCK[:12], "--side", "aa-1"])
        self.assertEqual(code, 0)
        text = buf.getvalue()
        self.assertIn(STOCK, text)
        self.assertIn("aa-1", text)
        self.assertIn("3.0.64", text)
        self.assertIn("box-aa", text)


if __name__ == "__main__":
    unittest.main()
