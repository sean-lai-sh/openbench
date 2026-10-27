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


def _smoke_row(pr: str, side: str, *, faults: int = 0, loaded: str = "bundled", scorable: str = "yes",
               smoke_score: str = "pass", box_score: str = "pass", box_cells: int = 30,
               match: str | None = None) -> dict:
    if match is None:
        match = "true" if smoke_score and smoke_score == box_score else "false"
    return {
        "pr": pr, "side": side, "cell_present": "yes", "provider_faults": str(faults),
        "provider_loaded_source": loaded, "scorable": scorable, "reason": "",
        "smoke_score": smoke_score, "box_score": box_score, "box_cells": str(box_cells),
        "score_match": match,
    }


def _box(solved: int, scored: int, cells: int | None = None, faults: int = 0) -> dict:
    from thesis.ab.step8_monorepo_smoke import box_score

    return {"cells": scored if cells is None else cells, "scored": scored, "solved": solved,
            "faults": faults, "score": box_score(solved, scored), "runs": ["box"]}


def _good_records(binary: Path, sha: str) -> list[dict]:
    from thesis.ab.step8_monorepo_build import sha256_file

    controls = [
        {"kind": "control", "sha": str(i) * 40, "control_match": "yes", "control_status": "pass", "used": "no"}
        for i in range(3)
    ]
    return controls + [{"kind": "monorepo", "sha": sha, "used": "yes", "binary_sha256": sha256_file(binary)}]


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
            self.assertEqual(clean["score_match"], "true")

            gated = assess_monorepo_row(row, layout="monorepo", provider=self.provider, binary=binary,
                                        loaded_source="none", smoke=_smoke_row("51062", "with"),
                                        build_reason="control step not run")
            self.assertEqual(gated["ready"], "no")
            self.assertIn("build gate: control step not run", gated["reason"])
            self.assertEqual(gated["scorable"], "no")

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

            mismatched = assess_monorepo_row(row, layout="monorepo", provider=self.provider, binary=binary,
                                             loaded_source="none",
                                             smoke=_smoke_row("51062", "with", box_score="fail"))
            self.assertEqual(mismatched["ready"], "yes")
            self.assertEqual(mismatched["score_match"], "false")
            self.assertEqual(mismatched["scorable"], "no")
            self.assertIn("smoke pass != box fail", mismatched["_scorable_reason"])

            # A hand-edited table that says true is recomputed from the two calls.
            edited = assess_monorepo_row(row, layout="monorepo", provider=self.provider, binary=binary,
                                         loaded_source="none",
                                         smoke=_smoke_row("51062", "with", box_score="fail", match="true"))
            self.assertEqual(edited["score_match"], "false")
            self.assertEqual(edited["scorable"], "no")

            no_box = assess_monorepo_row(row, layout="monorepo", provider=self.provider, binary=binary,
                                         loaded_source="none",
                                         smoke=_smoke_row("51062", "with", box_score="", box_cells=0))
            self.assertEqual(no_box["score_match"], "false")
            self.assertEqual(no_box["scorable"], "no")
            self.assertIn("no box data", no_box["_scorable_reason"])

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
            old_fields = dry.FIELDS
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
            binary = make_exec(dry.binary_path(bin_root, SHA_WITH))
            from thesis.ab.step8_monorepo_build import write_records

            no_builds = tmp / "no-builds.csv"
            builds = tmp / "monorepo-builds.csv"
            write_records(_good_records(binary, SHA_WITH), builds)
            with patch.object(dry, "trace_binary", return_value=("", "none")):
                gated = dry.run_monorepo(
                    [{"pr": "51062", "side": "with", "sha": SHA_WITH}], cache=tmp / "cache",
                    bin_root=bin_root, mirror=None, smoke_csv=tmp / "no-smoke.csv", builds_csv=no_builds,
                )
            self.assertEqual(gated[0]["ready"], "no")
            self.assertIn("build gate: control step not run", gated[0]["reason"])
            before = out.read_bytes()
            mono_out = tmp / "monorepo-dry-run.csv"
            with patch.object(dry, "trace_binary", return_value=("", "none")) as traced:
                rows = dry.refresh_monorepo(pins, rerun, mono_out, cache=tmp / "cache", bin_root=bin_root,
                                            mirror=None, smoke_csv=tmp / "no-smoke.csv", builds_csv=builds)
            self.assertEqual(traced.call_count, 1)
            # The full dry-run table is never rewritten by the monorepo pass.
            self.assertEqual(out.read_bytes(), before)
            written = _rows(mono_out)
            self.assertEqual(len(written), 2)
            self.assertEqual(list(written[0].keys()), dry.MONOREPO_FIELDS)
            with_row, without_row = written[0], written[1]
            self.assertEqual(with_row["group"], "monorepo")
            self.assertEqual(with_row["ready"], "yes")
            self.assertEqual(with_row["loaded_source"], "bundled")
            self.assertEqual(with_row["scorable"], "no")
            self.assertEqual(without_row["ready"], "no")
            self.assertIn("opencode binary missing", without_row["reason"])
            self.assertIn("monorepo sides 2 ready 1 scorable 0", dry.summarize_monorepo(rows))

    def test_full_dry_run_keeps_main_format(self):
        from thesis.ab import step8_pin_dry_run as dry

        # dry-run.csv keeps #160's columns; the four new columns are only in monorepo-dry-run.csv.
        self.assertEqual(dry.MONOREPO_FIELDS[: len(dry.FIELDS)], dry.FIELDS)
        for name in ("provider_mode", "bundled_provider", "score_match", "scorable"):
            self.assertNotIn(name, dry.FIELDS)
            self.assertIn(name, dry.MONOREPO_FIELDS)
        main_header = list(_rows(DEFAULT_OUT / "dry-run.csv")[0].keys())
        self.assertEqual(main_header, dry.FIELDS)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            out = tmp / "dry-run.csv"
            mono_out = tmp / "monorepo-dry-run.csv"
            with patch.object(dry, "seed_versions", return_value={}), \
                    patch.object(dry, "trace_binary", return_value=("", "none")):
                rows = dry.run_dry(DEFAULT_OUT / "pins.csv", DEFAULT_OUT / "rerun-1443.json", tmp / "cache",
                                   tmp / "src", "bun", out)
                mono = dry.refresh_monorepo(DEFAULT_OUT / "pins.csv", DEFAULT_OUT / "rerun-1443.json", mono_out,
                                            cache=tmp / "cache", bin_root=tmp / "src", mirror=None,
                                            smoke_csv=tmp / "none.csv", builds_csv=tmp / "none.csv")
            written = _rows(out)
            self.assertEqual(list(written[0].keys()), dry.FIELDS)
            deferred = [row for row in written if row["pr"] in monorepo.MONOREPO_PRS]
            self.assertEqual(len(deferred), 6)
            self.assertTrue(all(row["reason"].startswith("deferred") for row in deferred))
            self.assertEqual(len(rows), 594)
            self.assertEqual(list(_rows(mono_out)[0].keys()), dry.MONOREPO_FIELDS)
            self.assertEqual(len(mono), 6)

    def test_committed_tables(self):
        # Main's dry-run table from #160 is not rewritten: the six rows stay deferred there.
        main_dry = _rows(DEFAULT_OUT / "dry-run.csv")
        self.assertNotIn("provider_mode", main_dry[0])
        main_mono = [row for row in main_dry if row["pr"] in monorepo.MONOREPO_PRS]
        self.assertEqual(len(main_mono), 6)
        self.assertTrue(all(row["reason"].startswith("deferred") for row in main_mono))
        mono = _rows(DEFAULT_OUT / "monorepo-dry-run.csv")
        self.assertEqual(len(mono), 6)
        self.assertEqual({row["sha"] for row in mono}, {row["sha"] for row in main_mono})
        for row in mono:
            self.assertEqual(row["group"], "monorepo")
            self.assertEqual(row["provider_mode"], "bundled")
            self.assertTrue(row["bundled_provider"].startswith("@opencode/ai@2.0.2"))
            self.assertNotIn("deferred", row["reason"])
            self.assertIn(row["ready"], {"yes", "no"})
            self.assertTrue(row["reason"] or row["ready"] == "yes")
            # No smoke table is committed, so nothing is scorable yet.
            self.assertEqual(row["scorable"], "no")
            self.assertEqual(row["score_match"], "false")
        by_pr: dict[str, set[str]] = {}
        for row in mono:
            by_pr.setdefault(row["pr"], set()).add(row["bundled_provider"])
        self.assertTrue(all(len(labels) == 1 for labels in by_pr.values()))
        pins = _rows(DEFAULT_OUT / "pins.csv")
        deferred = [row for row in pins if row["pr"] in monorepo.MONOREPO_PRS]
        self.assertEqual({row["status"] for row in deferred}, {"deferred"})
        self.assertEqual({row["version"] for row in deferred}, {""})
        builds = _rows(DEFAULT_OUT / "monorepo-builds.csv")
        self.assertEqual(sorted(row["sha"] for row in builds), sorted(row["sha"] for row in mono))
        for row in builds:
            self.assertEqual(row["kind"], "monorepo")
            self.assertEqual(row["lockfile"], "bun.lock")
            self.assertRegex(row["lockfile_sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(row["used"], "no")
            self.assertEqual(row["binary_sha256"], "")


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
        box = _box(29, 30)
        clean = assess_side(side, "misleading-error", self._cell(), box)
        self.assertEqual((clean["provider_faults"], clean["call"], clean["scorable"]), (0, "solved", "yes"))
        self.assertEqual((clean["smoke_score"], clean["box_score"], clean["score_match"]), ("pass", "pass", "true"))
        faulted = assess_side(side, "misleading-error", self._cell(
            failure_class="infra", success=False, error="AI_APICallError: overloaded_error",
        ), box)
        self.assertEqual((faulted["provider_faults"], faulted["scorable"]), (1, "no"))
        timeout = assess_side(side, "misleading-error", self._cell(
            failure_class="hang", success=False, error="TimeoutError timed out. stream error",
        ), _box(0, 30))
        self.assertEqual((timeout["provider_faults"], timeout["smoke_score"], timeout["scorable"]),
                         (0, "fail", "yes"))
        unbundled = assess_side(side, "misleading-error", self._cell(provider_loaded_source=""), box)
        self.assertEqual(unbundled["scorable"], "no")
        missing = assess_side(side, "misleading-error", None, box)
        self.assertEqual((missing["cell_present"], missing["scorable"]), ("no", "no"))
        self.assertEqual(missing["score_match"], "false")
        compared = assess_side(side, "misleading-error", self._cell(), _box(29, 30))
        self.assertEqual((compared["box_solved"], compared["score_match"]), ("29/30", "true"))

    def test_mismatched_scoring_call_is_not_scorable(self):
        from thesis.ab.step8_monorepo_smoke import assess_side, smoke_scorable

        side = {"pr": "51062", "side": "with", "sha": SHA_WITH}
        # Smoke solved, box mostly failed: zero provider faults is not enough.
        row = assess_side(side, "misleading-error", self._cell(), _box(3, 30))
        self.assertEqual((row["provider_faults"], row["smoke_score"], row["box_score"]), (0, "pass", "fail"))
        self.assertEqual(row["score_match"], "false")
        self.assertEqual(row["scorable"], "no")
        self.assertIn("smoke pass != box fail", row["reason"])
        # The other direction, and a tie (which is fail on the box side).
        row = assess_side(side, "misleading-error", self._cell(failure_class="wrong_answer", success=False),
                          _box(20, 30))
        self.assertEqual((row["score_match"], row["scorable"]), ("false", "no"))
        row = assess_side(side, "misleading-error", self._cell(), _box(15, 30))
        self.assertEqual((row["box_score"], row["score_match"]), ("fail", "false"))
        # An infra smoke cell has no scoring call.
        row = assess_side(side, "misleading-error", self._cell(failure_class="infra", success=False),
                          _box(30, 30))
        self.assertEqual((row["smoke_score"], row["score_match"], row["scorable"]), ("", "false", "no"))
        # The table check refuses a mismatch even if score_match and scorable were edited.
        self.assertFalse(smoke_scorable(_smoke_row("51062", "with", box_score="fail", match="true"))[0])

    def test_missing_box_data_is_not_scorable(self):
        from thesis.ab.step8_monorepo_smoke import assess_side, box_summary, smoke_scorable

        side = {"pr": "51062", "side": "with", "sha": SHA_WITH}
        with tempfile.TemporaryDirectory() as tmp:
            box_dir = Path(tmp) / "box"
            empty = box_summary([box_dir], "51062", "with", "misleading-error")
            self.assertEqual((empty["cells"], empty["score"]), (0, ""))
            row = assess_side(side, "misleading-error", self._cell(), empty)
            self.assertEqual((row["box_score"], row["score_match"], row["scorable"]), ("", "false", "no"))
            self.assertIn("no box data for this side on main", row["reason"])
            # Box cells for another task or side do not count.
            _write(box_dir / "51062" / "with.jsonl", json.dumps(self._cell(task="other-task")) + "\n")
            _write(box_dir / "51062" / "without.jsonl", json.dumps(self._cell()) + "\n")
            self.assertEqual(box_summary([box_dir], "51062", "with", "misleading-error")["cells"], 0)
            # Box cells that are all infra give no scoring call either.
            _write(box_dir / "51062" / "with.jsonl",
                   json.dumps(self._cell(failure_class="infra", success=False)) + "\n")
            infra = box_summary([box_dir], "51062", "with", "misleading-error")
            self.assertEqual((infra["cells"], infra["scored"], infra["score"]), (1, 0, ""))
            row = assess_side(side, "misleading-error", self._cell(), infra)
            self.assertEqual(row["score_match"], "false")
            self.assertIn("all infra", row["reason"])
        self.assertFalse(smoke_scorable(_smoke_row("51062", "with", box_score="", box_cells=0))[0])

    def test_box_calls_come_from_main(self):
        from thesis.ab.step8_monorepo_smoke import box_summary, default_box_dirs

        dirs = default_box_dirs()
        names = {path.name for path in dirs}
        self.assertIn("step8-full413-1020-F01", names)
        self.assertNotIn("step8-vm-F03-1-1025-QUARANTINED", names)
        recorded = box_summary(dirs, "1443", "without", "trig-read-lines")
        self.assertGreater(recorded["scored"], 0)
        self.assertIn(recorded["score"], {"pass", "fail"})
        self.assertIn("step8-full413-1020-F01", recorded["runs"])
        # The three monorepo PRs have no box cells on main.
        for pr, task in (("51062", "misleading-error"), ("53166", "make-it-run"), ("55613", "taskflow")):
            for side in ("with", "without"):
                self.assertEqual(box_summary(dirs, pr, side, task)["cells"], 0)

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
            self.assertEqual(by_key[("51062", "with")]["score_match"], "true")
            self.assertEqual(by_key[("51062", "without")]["provider_faults"], 1)
            self.assertEqual(by_key[("51062", "without")]["scorable"], "no")
            self.assertEqual(by_key[("53166", "with")]["reason"], "smoke cell missing")
            report = Path(tmp) / "monorepo-smoke.csv"
            smoke.write_report(rows, report)
            loaded = smoke.load_smoke(report)
            self.assertTrue(smoke.smoke_scorable(loaded[("51062", "with")])[0])
            self.assertFalse(smoke.smoke_scorable(loaded[("51062", "without")])[0])
            self.assertIn("sides 6 provider-faults 1 scorable 1", smoke.summarize(rows))

    def test_launch_refused_without_build_gate(self):
        from thesis.ab import step8_monorepo_smoke as smoke

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(smoke, "run_smoke") as launched, redirect_stdout(StringIO()), \
                    patch("sys.stderr", new_callable=StringIO) as err:
                code = smoke.main(["--cache", str(Path(tmp) / "src"), "--out", str(Path(tmp) / "out"),
                                   "--builds", str(Path(tmp) / "none.csv"),
                                   "--report", str(Path(tmp) / "report.csv"),
                                   "--task-map", str(ROOT / "results/step8-full413-1020/task-map.csv")])
        self.assertEqual(code, 3)
        launched.assert_not_called()
        self.assertIn("control step not run", err.getvalue())

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


class FakeProbe:
    """Build info and loaded provider from a table, keyed by binary path."""

    def __init__(self, info=None, loaded=None):
        self.info = info or {}
        self.loaded_map = loaded or {}

    def build_info(self, binary):
        return self.info.get(str(binary), "2.0.29")

    def loaded(self, binary, sha, side, tag):
        return self.loaded_map.get(str(binary), "no @ai-sdk/anthropic opened")


class MonorepoBuildRecordTests(unittest.TestCase):
    CONTROLS = [{"pr": str(i), "side": "without", "sha": str(i) * 40} for i in (7, 8, 9)]

    def _setup(self, tmp: Path):
        cache = tmp / "src"
        for control in self.CONTROLS:
            make_exec(cache / "bin" / control["sha"] / "opencode")
        built: list[tuple[str, Path]] = []

        def build_fn(sha, where):
            built.append((sha, Path(where)))
            root = Path(where) / "worktrees" / sha
            if sha in {row["sha"] for row in self.CONTROLS}:
                make_legacy(root)
            else:
                make_monorepo(root)
            return make_exec(Path(where) / "bin" / sha / "opencode")

        return cache, built, build_fn

    def test_control_pass_builds_and_records(self):
        from thesis.ab import step8_monorepo_build as build

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cache, built, build_fn = self._setup(tmp)
            out = tmp / "builds.csv"
            with patch.object(build, "worktree_head", side_effect=lambda root: Path(root).name), \
                    redirect_stdout(StringIO()):
                code = build.run_build(pins_csv=DEFAULT_OUT / "pins.csv", cache=cache, out=out,
                                       controls=self.CONTROLS, build_fn=build_fn, probe=FakeProbe())
            self.assertEqual(code, 0)
            # Controls are rebuilt into control-rebuild, never over the existing binaries.
            for sha, where in built[:3]:
                self.assertEqual(where.name, "control-rebuild")
            self.assertEqual(len(built), 9)
            rows = _rows(out)
            controls = [row for row in rows if row["kind"] == "control"]
            sides = [row for row in rows if row["kind"] == "monorepo"]
            self.assertEqual(len(controls), 3)
            self.assertTrue(all(row["control_match"] == "yes" and row["control_status"] == "pass"
                                for row in controls))
            self.assertEqual(len(sides), 6)
            for row in sides:
                self.assertEqual(row["used"], "yes", row)
                self.assertEqual(row["worktree_head"], row["sha"])
                self.assertEqual(row["plan_kind"], "monorepo")
                self.assertEqual(row["lockfile"], "bun.lock")
                self.assertRegex(row["lockfile_sha256"], r"^[0-9a-f]{64}$")
                self.assertRegex(row["binary_sha256"], r"^[0-9a-f]{64}$")
                self.assertIn("bundled @opencode/ai@2.0.29", row["loaded_provider"])
            records = build.load_records(out)
            sha = sides[0]["sha"]
            binary = cache / "bin" / sha / "opencode"
            self.assertEqual(build.build_gate_reason(records, sha, binary), "")
            binary.write_text("#!/bin/sh\nexit 1\n")
            self.assertIn("binary sha256", build.build_gate_reason(records, sha, binary))
            self.assertEqual(build.build_gate_reason(records, "f" * 40, binary), "no build record")

    def _failed(self, probe) -> tuple[int, list[dict], list]:
        from thesis.ab import step8_monorepo_build as build

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cache, built, build_fn = self._setup(tmp)
            out = tmp / "builds.csv"
            probe = probe(cache)
            with patch.object(build, "worktree_head", side_effect=lambda root: Path(root).name), \
                    redirect_stdout(StringIO()), patch("sys.stderr", new_callable=StringIO):
                code = build.run_build(pins_csv=DEFAULT_OUT / "pins.csv", cache=cache, out=out,
                                       controls=self.CONTROLS, build_fn=build_fn, probe=probe)
            rows = _rows(out)
            gate = build.launch_gate(out, build.monorepo_sides(DEFAULT_OUT / "pins.csv"), cache)
        return code, rows, built, gate

    def _assert_failed(self, code, rows, built, gate, expected):
        self.assertEqual(code, 3)
        # No monorepo side was built after the failed control.
        self.assertEqual(len(built), 3)
        sides = [row for row in rows if row["kind"] == "monorepo"]
        self.assertEqual(len(sides), 6)
        self.assertTrue(all(row["used"] == "no" and row["binary_sha256"] == "" for row in sides))
        self.assertTrue(all(row["control_status"] == "fail" for row in rows))
        self.assertTrue(any(expected in row["reason"] for row in rows if row["kind"] == "control"))
        self.assertEqual(len(gate), 6)
        self.assertTrue(all("control step failed" in problem for problem in gate))

    def test_build_info_mismatch_fails_the_step(self):
        def probe(cache):
            rebuilt = cache.resolve() / "control-rebuild" / "bin" / self.CONTROLS[1]["sha"] / "opencode"
            return FakeProbe(info={str(rebuilt): "2.0.30"})

        self._assert_failed(*self._failed(probe), "build info '2.0.30' != existing '2.0.29'")

    def test_loaded_provider_mismatch_fails_the_step(self):
        def probe(cache):
            existing = cache / "bin" / self.CONTROLS[0]["sha"] / "opencode"
            rebuilt = cache.resolve() / "control-rebuild" / "bin" / self.CONTROLS[0]["sha"] / "opencode"
            return FakeProbe(loaded={str(existing): "@ai-sdk/anthropic@2.0.0 (strace)",
                                     str(rebuilt): "@ai-sdk/anthropic@3.0.71 (strace)"})

        self._assert_failed(*self._failed(probe), "loaded provider")

    def test_unverified_loaded_provider_fails_the_step(self):
        def probe(cache):
            rebuilt = cache.resolve() / "control-rebuild" / "bin" / self.CONTROLS[2]["sha"] / "opencode"
            return FakeProbe(loaded={str(rebuilt): "unverified (strace unavailable)"})

        self._assert_failed(*self._failed(probe), "loaded provider unverified")

    def test_too_few_controls_fails_the_step(self):
        from thesis.ab import step8_monorepo_build as build

        with tempfile.TemporaryDirectory() as tmp:
            ok, rows = build.run_controls(self.CONTROLS[:2], cache=Path(tmp), build_fn=lambda *a: None,
                                          probe=FakeProbe())
        self.assertFalse(ok)
        self.assertIn("need 3 existing builds", rows[0]["reason"])
        self.assertIn("control step failed", build.control_problem(rows))
        self.assertEqual(build.control_problem([]), "control step not run")

    def test_control_candidates_need_existing_binaries(self):
        from thesis.ab.step8_monorepo_build import control_candidates

        pins = _rows(DEFAULT_OUT / "pins.csv")
        pinned = [row for row in pins if row["status"] == "pinned"]
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            self.assertEqual(control_candidates(DEFAULT_OUT / "pins.csv", cache), [])
            for row in pinned[-4:]:
                make_exec(cache / "bin" / row["sha"] / "opencode")
            found = control_candidates(DEFAULT_OUT / "pins.csv", cache)
        self.assertEqual(len(found), 4)
        self.assertEqual(found[0]["sha"], pinned[-1]["sha"])
        self.assertTrue(all(row["pr"] not in monorepo.MONOREPO_PRS for row in found))

    def test_records_only_reads_lockfile_from_mirror(self):
        from thesis.ab import step8_monorepo_build as build

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _git(repo, "init", "-q")
            make_monorepo(repo, lock='{"lockfileVersion": 1}\n')
            _git(repo, "add", "-A")
            _git(repo, "commit", "-qm", "m")
            sha = _git(repo, "rev-parse", "HEAD")
            rows = build.records_only([{"pr": "51062", "side": "with", "sha": sha}], repo)
        import hashlib
        self.assertEqual(rows[0]["lockfile"], "bun.lock")
        self.assertEqual(rows[0]["lockfile_sha256"], hashlib.sha256(b'{"lockfileVersion": 1}\n').hexdigest())
        self.assertEqual(rows[0]["used"], "no")


if __name__ == "__main__":
    unittest.main()
