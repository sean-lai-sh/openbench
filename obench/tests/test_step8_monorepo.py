"""Provider-free path for the post-monorepo step-8 PRs (51062, 53166, 55613).

No model calls and no GCP. Monorepo trees are built in temp directories
(and a temp git repo for the mirror path); the smoke runner is faked.
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from thesis.ab import monorepo
from thesis.ab.step8_pins import DEFAULT_OUT

ROOT = Path(__file__).resolve().parents[2]
SHA_WITH = "328f74c2131ad700eebfa2f4b5ee64fe2cde78e2"
SHA_WITHOUT = "32b1a1bf85ed1b9e57438c248463daea0b25a94f"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_monorepo(root: Path, *, ai_version: str = "2.0.29", lock: str = "{}\n", anthropic: bool = True) -> Path:
    _write(root / "package.json", json.dumps({"name": "opencode", "packageManager": "bun@1.4.2"}))
    _write(root / "bun.lock", lock)
    _write(root / "packages/cli/package.json", json.dumps({"name": "@opencode/cli", "version": ai_version}))
    _write(
        root / "packages/cli/script/build.ts",
        'const singleFlag = process.argv.includes("--single")\n'
        'const skipWebUi = process.argv.includes("--skip-web-ui")\n',
    )
    _write(root / "packages/ai/package.json", json.dumps({"name": "@opencode/ai", "version": ai_version}))
    if anthropic:
        _write(root / "packages/ai/src/providers/anthropic.ts", "export const anthropic = 1\n")
    return root


def make_legacy(root: Path) -> Path:
    _write(root / "package.json", json.dumps({"name": "opencode", "packageManager": "bun@1.2.21"}))
    _write(root / "packages/opencode/script/build.ts", "--single\n")
    return root


def _rows(path: Path) -> list[dict]:
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def make_exec(path: Path) -> Path:
    _write(path, "#!/bin/sh\nexit 0\n")
    path.chmod(0o755)
    return path


def _git(repo: Path, *args: str) -> str:
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t")
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env,
    ).stdout.strip()


class LayoutDetectionTests(unittest.TestCase):
    def test_tree_layouts(self):
        with tempfile.TemporaryDirectory() as tmp:
            mono = make_monorepo(Path(tmp) / "mono")
            legacy = make_legacy(Path(tmp) / "legacy")
            both = make_monorepo(Path(tmp) / "both")
            _write(both / "packages/opencode/package.json", "{}")
            bare = Path(tmp) / "bare"
            _write(bare / "package.json", "{}")
            self.assertTrue(monorepo.is_monorepo_tree(mono))
            self.assertFalse(monorepo.is_monorepo_tree(legacy))
            self.assertFalse(monorepo.is_monorepo_tree(both))
            self.assertEqual(monorepo.layout_of_tree(mono), "monorepo")
            self.assertEqual(monorepo.layout_of_tree(legacy), "legacy")
            self.assertEqual(monorepo.layout_of_tree(both), "legacy")
            self.assertEqual(monorepo.layout_of_tree(bare), "unknown")
            self.assertEqual(monorepo.layout_of_tree(Path(tmp) / "nope"), "missing")

    def test_bundled_provider_for_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            mono = make_monorepo(Path(tmp) / "mono")
            provider = monorepo.bundled_provider_for_tree(mono)
            self.assertEqual(provider["package"], "@opencode/ai")
            self.assertEqual(provider["version"], "2.0.29")
            self.assertEqual(provider["source"], monorepo.ANTHROPIC_SOURCE)
            self.assertEqual(provider["tree"], "")
            self.assertFalse(provider["sdk_locked"])
            self.assertEqual(monorepo.bundled_reason("monorepo", provider), "")
            self.assertEqual(monorepo.bundled_label(provider), "@opencode/ai@2.0.29")

            no_source = make_monorepo(Path(tmp) / "nosrc", anthropic=False)
            self.assertIsNone(monorepo.bundled_provider_for_tree(no_source))
            self.assertIn("no bundled provider", monorepo.bundled_reason("monorepo", None))

            locked = make_monorepo(
                Path(tmp) / "locked",
                lock='{"packages": {"@ai-sdk/anthropic": ["@ai-sdk/anthropic@2.0.0"]}}\n',
            )
            provider = monorepo.bundled_provider_for_tree(locked)
            self.assertTrue(provider["sdk_locked"])
            self.assertIn("bun.lock still lists", monorepo.bundled_reason("monorepo", provider))
            self.assertIn("packages/opencode", monorepo.bundled_reason("legacy", None))
            self.assertIn("not found", monorepo.bundled_reason("missing", None))

    def test_mirror_layout_and_bundled_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _git(repo, "init", "-q")
            make_legacy(repo)
            _git(repo, "add", "-A")
            _git(repo, "commit", "-qm", "legacy")
            legacy_sha = _git(repo, "rev-parse", "HEAD")
            _git(repo, "rm", "-rq", "packages/opencode")
            make_monorepo(repo)
            _git(repo, "add", "-A")
            _git(repo, "commit", "-qm", "monorepo")
            mono_sha = _git(repo, "rev-parse", "HEAD")
            self.assertEqual(monorepo.layout_at(repo, legacy_sha), "legacy")
            self.assertEqual(monorepo.layout_at(repo, mono_sha), "monorepo")
            self.assertEqual(monorepo.layout_at(repo, "0" * 40), "missing")
            provider = monorepo.bundled_provider_at(repo, mono_sha)
            self.assertEqual(provider["version"], "2.0.29")
            self.assertEqual(provider["tree"], _git(repo, "rev-parse", f"{mono_sha}:packages/ai/src"))
            self.assertIsNone(monorepo.bundled_provider_at(repo, legacy_sha))
            # A git worktree records the same tree id.
            self.assertEqual(monorepo.bundled_provider_for_tree(repo)["tree"], provider["tree"])

    def test_monorepo_prs_are_the_deferred_prs(self):
        from thesis.ab.step8_pins import DEFERRED

        self.assertEqual(set(monorepo.MONOREPO_PRS), set(DEFERRED))


class MonorepoBuildTests(unittest.TestCase):
    def test_build_plan_uses_packages_cli(self):
        from thesis.ab.build_opencode import _stamp_current, build_plan

        with tempfile.TemporaryDirectory() as tmp:
            plan = build_plan(make_monorepo(Path(tmp) / "mono"))
            self.assertEqual(plan["kind"], "monorepo")
            self.assertEqual(plan["cwd"], "packages/cli")
            self.assertEqual(plan["args"], ["bun", "script/build.ts", "--single", "--skip-web-ui"])
            self.assertEqual(plan["bun"], "1.4.2")
            legacy = build_plan(make_legacy(Path(tmp) / "legacy"))
            self.assertEqual(legacy["kind"], "build.ts")
            self.assertEqual(legacy["cwd"], "packages/opencode")
        self.assertTrue(_stamp_current({"kind": "monorepo", "args": []}))

    def test_find_binary_reads_cli_dist(self):
        from thesis.ab import build_opencode
        from thesis.ab.errors import BuildError

        with tempfile.TemporaryDirectory() as tmp:
            root = make_monorepo(Path(tmp) / "mono")
            with self.assertRaises(BuildError):
                build_opencode._find_binary(root)
            for name in ("cli-linux-x64", "cli-linux-x64-baseline", "cli-darwin-arm64"):
                make_exec(root / "packages/cli/dist" / name / "bin/opencode")
            with patch.object(build_opencode, "_host", return_value=("linux", "x64", "amd64")), \
                    patch.object(build_opencode, "host_libc", return_value="glibc"):
                found = build_opencode._find_binary(root)
            self.assertEqual(found, root / "packages/cli/dist/cli-linux-x64/bin/opencode")
        self.assertEqual(
            build_opencode._dist_target(Path("x/cli-linux-x64-baseline-musl/bin/opencode")),
            {"os": "linux", "arch": "x64", "baseline": True, "musl": True},
        )
        self.assertEqual(
            build_opencode._dist_target(Path("x/opencode-darwin-arm64/bin/opencode"))["os"], "darwin",
        )


class RunnerPathTests(unittest.TestCase):
    def _state(self):
        return {
            "ok": True,
            "harness": "opencode",
            "binary": "/bin/true",
            "proxy": {"needs_sdk": True, "anthropic_sdk": "latest", "port": 1},
        }

    def test_decorate_toolchain_goes_provider_free(self):
        from thesis.ab import run_ab

        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            make_monorepo(cache / "worktrees" / SHA_WITH)
            state, error = run_ab._decorate_toolchain(self._state(), cache, SHA_WITH, "")
            self.assertIsNone(error)
            proxy = state["proxy"]
            self.assertTrue(proxy["provider_bundled"])
            self.assertFalse(proxy["needs_sdk"])
            for key in ("anthropic_sdk", "provider_pins", "sdk_install_alias", "sdk_install_gate"):
                self.assertNotIn(key, proxy)
            self.assertEqual(proxy["provider_loaded_source"], "bundled")
            self.assertEqual(proxy["bundled_provider_version"], "2.0.29")
            self.assertEqual(proxy["pin_source"], monorepo.PIN_SOURCE)
            self.assertNotIn("anthropic", state["toolchain"])
            self.assertEqual(state["toolchain"]["provider_bundled"], "@opencode/ai@2.0.29")

            spec = {"sha": SHA_WITH, "side": "with", "pr": "51062"}
            overlaid = run_ab._overlay_provider_pin(state, cache, spec)
            self.assertIs(overlaid, state)
            self.assertIs(run_ab._fail_closed_unpinned(state, cache, spec), state)
            # The default preflight is the needs_sdk model call; it is skipped.
            self.assertIsNone(run_ab._default_preflight("/bin/true", state))

    def test_decorate_toolchain_fails_closed_without_provider(self):
        from thesis.ab import run_ab

        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            make_monorepo(cache / "worktrees" / SHA_WITH, anthropic=False)
            state, error = run_ab._decorate_toolchain(self._state(), cache, SHA_WITH, "")
            self.assertIn("monorepo: no bundled provider", error)
            self.assertNotIn("provider_bundled", state["proxy"])
            failed = run_ab._fail_closed_unpinned(
                {"ok": True, "harness": "opencode", "proxy": {"needs_sdk": False}},
                cache, {"sha": SHA_WITH},
            )
            self.assertFalse(failed["ok"])
            self.assertEqual(failed["status"], "infra")

    def test_legacy_tree_is_unchanged(self):
        from thesis.ab import run_ab

        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            make_legacy(cache / "worktrees" / SHA_WITH)
            with patch.object(run_ab, "anthropic_pin_for_tree", return_value="2.0.0"):
                state, error = run_ab._decorate_toolchain(self._state(), cache, SHA_WITH, "")
            self.assertIsNone(error)
            self.assertEqual(state["proxy"]["anthropic_sdk"], "2.0.0")
            self.assertNotIn("provider_bundled", state["proxy"])

    def test_per_cell_logging(self):
        from thesis.ab.run_ab import attach_provider_pin

        provider = {"package": "@opencode/ai", "version": "2.0.29", "tree": "0081539dc8aa" + "0" * 28}
        proxy = monorepo.bundled_proxy({"anthropic_sdk": "2.0.0", "provider_pins": {"x": "1"}}, provider)
        row: dict = {"task": "misleading-error"}
        attach_provider_pin(row, {"proxy": proxy})
        self.assertEqual(row["provider_loaded_source"], "bundled")
        self.assertEqual(row["bundled_provider_package"], "@opencode/ai")
        self.assertEqual(row["bundled_provider_version"], "2.0.29")
        self.assertEqual(row["bundled_provider_tree"], provider["tree"])
        self.assertEqual(row["pin_source"], monorepo.PIN_SOURCE)
        self.assertNotIn("provider_versions", row)
        self.assertNotIn("provider_pin_sha256", row)

        pinned: dict = {}
        attach_provider_pin(pinned, {"proxy": {"pin_source": "nearest_box_build"}})
        self.assertEqual(pinned, {"pin_source": "nearest_box_build"})
        for field in monorepo.CELL_FIELDS:
            self.assertNotIn(field, pinned)

        leaked = {"provider_versions": {"@ai-sdk/anthropic": "3.0.71"}}
        monorepo.attach_bundled_provider(leaked, proxy)
        self.assertEqual(leaked["provider_loaded_source"], "separate_install")
        self.assertEqual(leaked["failure_class"], "infra")

        # The #156 runtime probe: "none" is the bundled case; a traced load is not.
        probed: dict = {"provider_loaded_source": "none", "failure_class": "solved"}
        attach_provider_pin(probed, {"proxy": proxy})
        self.assertEqual(probed["provider_loaded_source"], "bundled")
        self.assertEqual(probed["provider_loaded_probe"], "none")
        self.assertEqual(probed["failure_class"], "solved")
        self.assertNotIn("provider_loaded_mismatch", probed)

        traced: dict = {"provider_loaded_source": "strace", "provider_loaded_version": "3.0.71",
                        "failure_class": "solved", "error": "x"}
        attach_provider_pin(traced, {"proxy": proxy})
        self.assertEqual(traced["provider_loaded_source"], "separate_install")
        self.assertEqual(traced["provider_loaded_probe"], "strace")
        self.assertEqual(traced["failure_class"], "infra")
        self.assertIn("provider_bundled_mismatch: loaded @ai-sdk/anthropic@3.0.71", traced["provider_loaded_mismatch"])
        self.assertIn("provider_bundled_mismatch", traced["error"])


def _smoke_row(pr: str, side: str, *, faults: int = 0, loaded: str = "bundled", scorable: str = "yes") -> dict:
    return {
        "pr": pr, "side": side, "cell_present": "yes", "provider_faults": str(faults),
        "provider_loaded_source": loaded, "scorable": scorable, "reason": "",
    }


class DryRunMonorepoTests(unittest.TestCase):
    provider = {"package": "@opencode/ai", "version": "2.0.29", "tree": "a" * 40, "sdk_locked": False}

    def test_missing_binary_is_not_ready(self):
        from thesis.ab.step8_pin_dry_run import assess_monorepo_row

        row = {"pr": "51062", "side": "with", "sha": SHA_WITH, "batch": "F16-2"}
        out = assess_monorepo_row(
            row, layout="monorepo", provider=self.provider, binary=Path("/nonexistent/opencode"),
        )
        self.assertEqual(out["ready"], "no")
        self.assertIn("opencode binary missing", out["reason"])
        self.assertEqual(out["provider_mode"], "bundled")
        self.assertEqual(out["pin_resolved"], "bundled")
        self.assertEqual(out["scorable"], "no")
        self.assertNotIn("deferred", out["reason"])

    def test_ready_and_scorable_needs_zero_fault_smoke(self):
        from thesis.ab.step8_pin_dry_run import assess_monorepo_row

        row = {"pr": "51062", "side": "with", "sha": SHA_WITH}
        with tempfile.TemporaryDirectory() as tmp:
            binary = make_exec(Path(tmp) / "opencode")
            no_smoke = assess_monorepo_row(row, layout="monorepo", provider=self.provider, binary=binary,
                                           loaded_source="none")
            self.assertEqual(no_smoke["ready"], "yes")
            self.assertEqual(no_smoke["loaded_check"], "pass")
            self.assertEqual(no_smoke["loaded_source"], "bundled")
            self.assertEqual(no_smoke["scorable"], "no")
            self.assertEqual(no_smoke["_scorable_reason"], "smoke not run")

            clean = assess_monorepo_row(row, layout="monorepo", provider=self.provider, binary=binary,
                                        loaded_source="none", smoke=_smoke_row("51062", "with"))
            self.assertEqual(clean["scorable"], "yes")

            faulted = assess_monorepo_row(row, layout="monorepo", provider=self.provider, binary=binary,
                                          loaded_source="none", smoke=_smoke_row("51062", "with", faults=1))
            self.assertEqual(faulted["ready"], "yes")
            self.assertEqual(faulted["scorable"], "no")
            self.assertIn("provider fault", faulted["_scorable_reason"])

            leaked = assess_monorepo_row(row, layout="monorepo", provider=self.provider, binary=binary,
                                         loaded_version="3.0.71", loaded_source="strace",
                                         smoke=_smoke_row("51062", "with"))
            self.assertEqual(leaked["ready"], "no")
            self.assertEqual(leaked["loaded_check"], "mismatch")
            self.assertEqual(leaked["scorable"], "no")

            legacy = assess_monorepo_row(row, layout="legacy", provider=None, binary=binary,
                                         smoke=_smoke_row("51062", "with"))
            self.assertEqual(legacy["ready"], "no")
            self.assertIn("monorepo:", legacy["reason"])
            self.assertEqual(legacy["scorable"], "no")

    def test_sides_must_bundle_the_same_provider(self):
        from thesis.ab.step8_pin_dry_run import assess_monorepo_row, check_pr_providers

        with tempfile.TemporaryDirectory() as tmp:
            binary = make_exec(Path(tmp) / "opencode")
            other = dict(self.provider, tree="b" * 40)
            rows = [
                assess_monorepo_row({"pr": "51062", "side": "with", "sha": SHA_WITH}, layout="monorepo",
                                    provider=self.provider, binary=binary, loaded_source="none",
                                    smoke=_smoke_row("51062", "with")),
                assess_monorepo_row({"pr": "51062", "side": "without", "sha": SHA_WITHOUT}, layout="monorepo",
                                    provider=other, binary=binary, loaded_source="none",
                                    smoke=_smoke_row("51062", "without")),
            ]
            check_pr_providers(rows)
            for row in rows:
                self.assertEqual(row["ready"], "no")
                self.assertEqual(row["scorable"], "no")
                self.assertIn("differs between sides", row["reason"])

    def test_locate_prefers_worktree_then_mirror(self):
        from thesis.ab.step8_pin_dry_run import locate_monorepo

        with tempfile.TemporaryDirectory() as tmp:
            bin_root = Path(tmp) / "src"
            self.assertEqual(locate_monorepo(SHA_WITH, bin_root=bin_root, mirror=None), ("missing", None, ""))
            make_monorepo(bin_root / "worktrees" / SHA_WITH)
            layout, provider, where = locate_monorepo(SHA_WITH, bin_root=bin_root, mirror=None)
            self.assertEqual((layout, where), ("monorepo", "worktree"))
            self.assertEqual(provider["version"], "2.0.29")

    def test_refresh_rewrites_only_monorepo_rows(self):
        from thesis.ab import step8_pin_dry_run as dry

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            pins = tmp / "pins.csv"
            with pins.open("w", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=["status", "batch", "pr", "side", "sha", "version"])
                writer.writeheader()
                writer.writerow({"status": "pinned", "batch": "F03-2", "pr": "3251", "side": "with",
                                 "sha": "1" * 40, "version": "2.0.0"})
                writer.writerow({"status": "deferred", "batch": "F16-2", "pr": "51062", "side": "with",
                                 "sha": SHA_WITH, "version": ""})
                writer.writerow({"status": "deferred", "batch": "F16-2", "pr": "51062", "side": "without",
                                 "sha": SHA_WITHOUT, "version": ""})
            rerun = tmp / "rerun.json"
            rerun.write_text(json.dumps({"pr": "1443", "do_not_run": True, "version": "2.0.0-beta.11",
                                         "sides": []}))
            out = tmp / "dry-run.csv"
            old_fields = dry.FIELDS[: dry.FIELDS.index("reason") + 1]
            with out.open("w", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=old_fields)
                writer.writeheader()
                writer.writerow({"group": "F03-2-F16", "pr": "3251", "side": "with", "sha": "1" * 40,
                                 "version": "2.0.0", "ready": "no", "reason": "opencode binary missing at x"})
                for side, sha in (("with", SHA_WITH), ("without", SHA_WITHOUT)):
                    writer.writerow({"group": "F03-2-F16", "pr": "51062", "side": side, "sha": sha,
                                     "ready": "no", "reason": "deferred post-monorepo; not pinned and not seeded"})
            bin_root = tmp / "src"
            make_monorepo(bin_root / "worktrees" / SHA_WITH)
            make_monorepo(bin_root / "worktrees" / SHA_WITHOUT)
            make_exec(dry.binary_path(bin_root, SHA_WITH))
            with patch.object(dry, "trace_binary", return_value=("", "none")) as traced:
                rows = dry.refresh_monorepo(pins, rerun, out, cache=tmp / "cache", bin_root=bin_root,
                                            mirror=None, smoke_csv=tmp / "no-smoke.csv")
            self.assertEqual(traced.call_count, 1)
            written = _rows(out)
            self.assertEqual(list(written[0].keys()), dry.FIELDS)
            self.assertEqual(written[0]["provider_mode"], "pinned")
            self.assertEqual(written[0]["version"], "2.0.0")
            with_row, without_row = written[1], written[2]
            self.assertEqual(with_row["group"], "monorepo")
            self.assertEqual(with_row["ready"], "yes")
            self.assertEqual(with_row["loaded_source"], "bundled")
            self.assertEqual(with_row["scorable"], "no")
            self.assertEqual(without_row["ready"], "no")
            self.assertIn("opencode binary missing", without_row["reason"])
            self.assertIn("monorepo sides 2 ready 1 scorable 0", dry.summarize(rows))

    def test_committed_tables(self):
        dry = _rows(DEFAULT_OUT / "dry-run.csv")
        mono = [row for row in dry if row["pr"] in monorepo.MONOREPO_PRS]
        self.assertEqual(len(mono), 6)
        for row in mono:
            self.assertEqual(row["group"], "monorepo")
            self.assertEqual(row["provider_mode"], "bundled")
            self.assertTrue(row["bundled_provider"].startswith("@opencode/ai@2.0.2"))
            self.assertNotIn("deferred", row["reason"])
            self.assertIn(row["ready"], {"yes", "no"})
            self.assertTrue(row["reason"] or row["ready"] == "yes")
            # No smoke table is committed, so nothing is scorable yet.
            self.assertEqual(row["scorable"], "no")
        by_pr: dict[str, set[str]] = {}
        for row in mono:
            by_pr.setdefault(row["pr"], set()).add(row["bundled_provider"])
        self.assertTrue(all(len(labels) == 1 for labels in by_pr.values()))
        self.assertTrue(all(row["provider_mode"] == "pinned" for row in dry if row not in mono))
        pins = _rows(DEFAULT_OUT / "pins.csv")
        deferred = [row for row in pins if row["pr"] in monorepo.MONOREPO_PRS]
        self.assertEqual({row["status"] for row in deferred}, {"deferred"})
        self.assertEqual({row["version"] for row in deferred}, {""})


class SmokeTests(unittest.TestCase):
    def _cell(self, **extra) -> dict:
        cell = {
            "task": "misleading-error", "trial": 1, "cell_seed": 1, "failure_class": "solved",
            "success": True, "provider_loaded_source": "bundled",
            "bundled_provider_package": "@opencode/ai", "bundled_provider_version": "2.0.29",
            "bundled_provider_tree": "a" * 40, "pin_source": monorepo.PIN_SOURCE,
        }
        cell.update(extra)
        return cell

    def test_assess_side_gates_scorable_on_provider_faults(self):
        from thesis.ab.step8_monorepo_smoke import assess_side

        side = {"pr": "51062", "side": "with", "sha": SHA_WITH}
        box = {"cells": 0, "solved": 0, "faults": 0}
        clean = assess_side(side, "misleading-error", self._cell(), box)
        self.assertEqual((clean["provider_faults"], clean["call"], clean["scorable"]), (0, "solved", "yes"))
        self.assertEqual(clean["call_matches_box"], "no box cells")
        faulted = assess_side(side, "misleading-error", self._cell(
            failure_class="infra", success=False, error="AI_APICallError: overloaded_error",
        ), box)
        self.assertEqual((faulted["provider_faults"], faulted["scorable"]), (1, "no"))
        timeout = assess_side(side, "misleading-error", self._cell(
            failure_class="hang", success=False, error="TimeoutError timed out. stream error",
        ), box)
        self.assertEqual((timeout["provider_faults"], timeout["scorable"]), (0, "yes"))
        unbundled = assess_side(side, "misleading-error", self._cell(provider_loaded_source=""), box)
        self.assertEqual(unbundled["scorable"], "no")
        missing = assess_side(side, "misleading-error", None, box)
        self.assertEqual((missing["cell_present"], missing["scorable"]), ("no", "no"))
        compared = assess_side(side, "misleading-error", self._cell(), {"cells": 30, "solved": 29, "faults": 0})
        self.assertEqual((compared["box_solved"], compared["call_matches_box"]), ("29/30", "yes"))

    def test_smoke_scorable_rechecks_counts(self):
        from thesis.ab.step8_monorepo_smoke import smoke_scorable

        self.assertEqual(smoke_scorable(None), (False, "smoke not run"))
        self.assertTrue(smoke_scorable(_smoke_row("51062", "with"))[0])
        self.assertFalse(smoke_scorable(_smoke_row("51062", "with", faults=2, scorable="yes"))[0])
        self.assertFalse(smoke_scorable(_smoke_row("51062", "with", loaded="separate_install"))[0])
        self.assertFalse(smoke_scorable(dict(_smoke_row("51062", "with"), cell_present="no"))[0])

    def test_commands_collect_and_report(self):
        from thesis.ab import step8_monorepo_smoke as smoke

        sides = smoke.monorepo_sides(DEFAULT_OUT / "pins.csv")
        self.assertEqual(len(sides), 6)
        self.assertEqual([row["side"] for row in sides[:2]], ["without", "with"])
        tasks = {"51062": "misleading-error", "53166": "make-it-run", "55613": "taskflow"}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            commands = smoke.smoke_commands(prs=Path("prs.csv"), task_map=Path("map.csv"), tasks=tasks,
                                            out=out, cache=Path("src"), model="claude-sonnet-5-5")
            self.assertEqual(len(commands), 3)
            for cmd, pr in zip(commands, monorepo.MONOREPO_PRS):
                self.assertIn("thesis.ab.run_ab", cmd)
                self.assertEqual(cmd[cmd.index("--pr") + 1], pr)
                self.assertEqual(cmd[cmd.index("--trials") + 1], "1")
                self.assertEqual(cmd[cmd.index("--tasks") + 1], tasks[pr])
            launched: list[list[str]] = []
            self.assertEqual(smoke.run_smoke(commands, runner=lambda cmd: launched.append(cmd) or 0), [0, 0, 0])
            self.assertEqual(launched, commands)

            cell = smoke._cell_path(out, "51062", "with", "misleading-error", 1)
            _write(cell, json.dumps(self._cell()))
            _write(out / "51062" / "without.jsonl", json.dumps(self._cell(
                failure_class="infra", success=False, error="Unhandled chunk type: foo",
            )) + "\n")
            box = Path(tmp) / "box"
            _write(box / "51062" / "with.jsonl",
                   "\n".join(json.dumps(self._cell(failure_class=c)) for c in ("solved", "wrong_answer", "solved")))
            rows = smoke.collect(out, sides, tasks, [box])
            by_key = {(row["pr"], row["side"]): row for row in rows}
            self.assertEqual(by_key[("51062", "with")]["scorable"], "yes")
            self.assertEqual(by_key[("51062", "with")]["box_solved"], "2/3")
            self.assertEqual(by_key[("51062", "without")]["provider_faults"], 1)
            self.assertEqual(by_key[("51062", "without")]["scorable"], "no")
            self.assertEqual(by_key[("53166", "with")]["reason"], "smoke cell missing")
            report = Path(tmp) / "monorepo-smoke.csv"
            smoke.write_report(rows, report)
            loaded = smoke.load_smoke(report)
            self.assertTrue(smoke.smoke_scorable(loaded[("51062", "with")])[0])
            self.assertFalse(smoke.smoke_scorable(loaded[("51062", "without")])[0])
            self.assertIn("sides 6 provider-faults 1 scorable 1", smoke.summarize(rows))

    def test_plan_mode_launches_nothing(self):
        from thesis.ab import step8_monorepo_smoke as smoke

        with patch.object(smoke, "run_smoke") as launched, redirect_stdout(StringIO()) as printed:
            self.assertEqual(smoke.main(["--cache", "src", "--plan",
                                         "--task-map", str(ROOT / "results/step8-full413-1020/task-map.csv")]), 0)
        launched.assert_not_called()
        lines = printed.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(all("--trials 1" in line for line in lines))
        self.assertIn("--tasks misleading-error", lines[0])


if __name__ == "__main__":
    unittest.main()
