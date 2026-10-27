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


PARITY_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "step8-scoring-parity" / "box-run"
PARITY_PRS = ("4001", "4002")
PARITY_OK = (True, "")


def _smoke_row(pr: str, side: str, *, faults: int = 0, loaded: str = "bundled", present: str = "yes",
               smoke_ok: str = "yes", scorable: str = "yes") -> dict:
    return {
        "pr": pr, "side": side, "cell_present": present, "provider_faults": str(faults),
        "provider_loaded_source": loaded, "smoke_ok": smoke_ok, "scorable": scorable, "reason": "",
    }


def _all_smoke(**overrides) -> dict:
    """Six clean smoke rows; ``overrides`` maps ``(pr, side)`` to row changes."""
    rows = {}
    for pr in monorepo.MONOREPO_PRS:
        for side in ("without", "with"):
            row = _smoke_row(pr, side)
            row.update(overrides.get(f"{pr}_{side}", {}))
            rows[(pr, side)] = row
    return rows


def _good_records(binary: Path, sha: str) -> list[dict]:
    from thesis.ab.step8_monorepo_build import sha256_file

    controls = [
        {"kind": "control", "sha": str(i) * 40, "control_match": "yes", "control_status": "pass", "used": "no"}
        for i in range(3)
    ]
    return controls + [{"kind": "monorepo", "sha": sha, "used": "yes", "binary_sha256": sha256_file(binary)}]


class ScoringParityTests(unittest.TestCase):
    def test_fixture_outputs_reproduce_the_box(self):
        from thesis.ab.step8_scoring_parity import parity_result, run_parity

        rows = run_parity(PARITY_FIXTURE, PARITY_PRS)
        self.assertEqual(len(rows), 7)
        self.assertEqual({row["box_call"] for row in rows}, {"pass", "fail"})
        self.assertTrue(all(row["match"] == "true" for row in rows))
        self.assertEqual([row["replay_failure_class"] for row in rows],
                         [row["box_failure_class"] for row in rows])
        self.assertEqual(parity_result(rows, PARITY_PRS), (True, ""))

    def test_replay_uses_the_runner_scoring_path(self):
        from thesis.ab.step8_scoring_parity import box_cells, replay_cell

        cells = {(side, row["trial"]): row for side, row in box_cells(PARITY_FIXTURE, "4001")}
        passed = replay_cell(dict(cells[("without", 1)], failure_class="bogus", success=None))
        self.assertEqual((passed["failure_class"], passed["success"], passed["score"]), ("solved", True, 1.0))
        failed = replay_cell(cells[("without", 2)])
        self.assertEqual((failed["failure_class"], failed["success"], failed["score"]), ("wrong_answer", False, 0.5))
        # A checker crash with no agreeing OBENCH_VERDICT line is infra, not a pass.
        crashed = replay_cell(cells[("with", 1)])
        self.assertEqual(crashed["failure_class"], "infra")
        self.assertTrue(crashed["failure_reason"].startswith("checker_crash"))
        # Exit 0 without a verdict line is not a pass for a thesis task.
        no_verdict = replay_cell(dict(cells[("with", 2)], checker_stdout="SCORE: 1.0\n"))
        self.assertNotEqual(no_verdict["failure_class"], "solved")
        # The saved row is not modified.
        self.assertEqual(cells[("without", 1)]["failure_class"], "solved")

    def test_one_mismatched_cell_fails_parity(self):
        from thesis.ab.step8_scoring_parity import parity_result, run_parity

        with tempfile.TemporaryDirectory() as tmp:
            box = Path(tmp) / "box-run"
            for path in PARITY_FIXTURE.rglob("*.jsonl"):
                _write(box / path.relative_to(PARITY_FIXTURE), path.read_text())
            # The box recorded a pass, but its saved checker output is a fail.
            target = box / "4002" / "with.jsonl"
            lines = target.read_text().splitlines()
            tampered = json.loads(lines[1])
            tampered.update({"failure_class": "solved", "success": True})
            lines[1] = json.dumps(tampered)
            target.write_text("\n".join(lines) + "\n")
            rows = run_parity(box, PARITY_PRS)
        bad = [row for row in rows if row["match"] == "false"]
        self.assertEqual(len(bad), 1)
        self.assertEqual((bad[0]["box_call"], bad[0]["replay_call"]), ("pass", "fail"))
        passed, reason = parity_result(rows, PARITY_PRS)
        self.assertFalse(passed)
        self.assertIn("6/7 cells", reason)

    def test_parity_needs_two_prs_with_cells(self):
        from thesis.ab.step8_scoring_parity import parity_result, run_parity

        self.assertEqual(parity_result([]), (False, "scoring parity not run"))
        one = run_parity(PARITY_FIXTURE, ("4001",))
        self.assertIn("needs 2 PRs", parity_result(one)[1])
        missing = run_parity(PARITY_FIXTURE, ("4001", "9999"))
        self.assertIn("no cells for 9999", parity_result(missing, ("4001", "9999"))[1])

    def test_table_roundtrip_and_cli(self):
        from thesis.ab import step8_scoring_parity as parity

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "scoring-parity.csv"
            with redirect_stdout(StringIO()) as printed:
                code = parity.main(["--box-run", str(PARITY_FIXTURE), "--pr", "4001", "--pr", "4002",
                                    "--out", str(out)])
            self.assertEqual(code, 0)
            self.assertIn("scoring_parity pass: 7/7 cells", printed.getvalue())
            self.assertEqual(parity.parity_from_table(out), (True, ""))
            # A hand-edited match column does not hide a call mismatch.
            rows = _rows(out)
            rows[0]["replay_call"] = "fail" if rows[0]["box_call"] == "pass" else "pass"
            parity.write_parity(rows, out)
            self.assertFalse(parity.parity_from_table(out)[0])

    def test_committed_parity_table(self):
        from thesis.ab.step8_scoring_parity import DEFAULT_BOX_RUN, DEFAULT_PRS, parity_result, run_parity

        committed = _rows(DEFAULT_OUT / "scoring-parity.csv")
        self.assertEqual(sorted({row["pr"] for row in committed}), sorted(DEFAULT_PRS))
        self.assertEqual({row["box_run"] for row in committed}, {DEFAULT_BOX_RUN.name})
        self.assertEqual(len(committed), 120)
        self.assertEqual(parity_result(committed, DEFAULT_PRS), (True, ""))
        # Reproducible from the box's saved outputs on main.
        fresh = run_parity(DEFAULT_BOX_RUN, DEFAULT_PRS)
        self.assertEqual([(r["pr"], r["side"], str(r["trial"]), r["replay_call"]) for r in fresh],
                         [(r["pr"], r["side"], r["trial"], r["replay_call"]) for r in committed])


class DryRunMonorepoTests(unittest.TestCase):
    provider = {"package": "@opencode/ai", "version": "2.0.29", "tree": "a" * 40, "sdk_locked": False}

    def test_missing_binary_is_not_ready(self):
        from thesis.ab.step8_pin_dry_run import assess_monorepo_row

        row = {"pr": "51062", "side": "with", "sha": SHA_WITH, "batch": "F16-2"}
        out = assess_monorepo_row(
            row, layout="monorepo", provider=self.provider, binary=Path("/nonexistent/opencode"),
        )
        self.assertEqual(out["side_key"], "51062:with")
        self.assertEqual(out["ready"], "no")
        self.assertIn("opencode binary missing", out["reason"])
        self.assertEqual(out["provider_mode"], "bundled")
        self.assertEqual(out["pin_resolved"], "bundled")
        self.assertEqual(out["scorable"], "excluded")
        self.assertNotIn("deferred", out["reason"])

    def test_readiness(self):
        from thesis.ab.step8_pin_dry_run import assess_monorepo_row

        row = {"pr": "51062", "side": "with", "sha": SHA_WITH}
        with tempfile.TemporaryDirectory() as tmp:
            binary = make_exec(Path(tmp) / "opencode")
            ready = assess_monorepo_row(row, layout="monorepo", provider=self.provider, binary=binary,
                                        loaded_source="none")
            self.assertEqual((ready["ready"], ready["loaded_check"], ready["loaded_source"]),
                             ("yes", "pass", "bundled"))
            gated = assess_monorepo_row(row, layout="monorepo", provider=self.provider, binary=binary,
                                        loaded_source="none", build_reason="control step not run")
            self.assertEqual(gated["ready"], "no")
            self.assertIn("build gate: control step not run", gated["reason"])
            leaked = assess_monorepo_row(row, layout="monorepo", provider=self.provider, binary=binary,
                                         loaded_version="3.0.71", loaded_source="strace")
            self.assertEqual((leaked["ready"], leaked["loaded_check"]), ("no", "mismatch"))
            legacy = assess_monorepo_row(row, layout="legacy", provider=None, binary=binary)
            self.assertEqual(legacy["ready"], "no")
            self.assertIn("monorepo:", legacy["reason"])

    def _six_ready(self, binary: Path) -> list[dict]:
        from thesis.ab.step8_pin_dry_run import assess_monorepo_row

        return [
            assess_monorepo_row({"pr": pr, "side": side, "sha": f"{pr}{side}"}, layout="monorepo",
                                provider=self.provider, binary=binary, loaded_source="none")
            for pr in monorepo.MONOREPO_PRS for side in ("without", "with")
        ]

    def test_all_six_scorable_only_with_clean_smoke_and_parity(self):
        from thesis.ab.step8_pin_dry_run import apply_monorepo_gate

        with tempfile.TemporaryDirectory() as tmp:
            binary = make_exec(Path(tmp) / "opencode")
            rows = apply_monorepo_gate(self._six_ready(binary), _all_smoke(), PARITY_OK)
            self.assertEqual({row["scorable"] for row in rows}, {"yes"})
            self.assertEqual({row["scoring_parity"] for row in rows}, {"pass"})

            # One faulted smoke cell excludes all three PRs.
            rows = apply_monorepo_gate(self._six_ready(binary),
                                       _all_smoke(**{"55613_with": {"provider_faults": "1"}}), PARITY_OK)
            self.assertEqual({row["scorable"] for row in rows}, {"excluded"})
            self.assertIn("55613 with: smoke shows 1 provider fault", rows[0]["_scorable_reason"])

            # A load that was not bundled, a missing cell, or no smoke at all: excluded.
            for override in ({"51062_without": {"provider_loaded_source": "separate_install"}},
                             {"53166_with": {"cell_present": "no"}}):
                rows = apply_monorepo_gate(self._six_ready(binary), _all_smoke(**override), PARITY_OK)
                self.assertEqual({row["scorable"] for row in rows}, {"excluded"})
            smoke = _all_smoke()
            del smoke[("53166", "without")]
            rows = apply_monorepo_gate(self._six_ready(binary), smoke, PARITY_OK)
            self.assertEqual({row["scorable"] for row in rows}, {"excluded"})
            self.assertIn("53166 without: smoke not run", rows[0]["_scorable_reason"])

            # Clean smoke, failed parity: excluded.
            rows = apply_monorepo_gate(self._six_ready(binary), _all_smoke(),
                                       (False, "scoring parity 6/7 cells"))
            self.assertEqual({row["scorable"] for row in rows}, {"excluded"})
            self.assertEqual({row["scoring_parity"] for row in rows}, {"fail"})
            self.assertIn("scoring parity 6/7 cells", rows[0]["_scorable_reason"])

            # A hand-edited smoke_ok/scorable column does not hide a provider fault.
            edited = _all_smoke(**{"51062_with": {"provider_faults": "2", "smoke_ok": "yes", "scorable": "yes"}})
            rows = apply_monorepo_gate(self._six_ready(binary), edited, PARITY_OK)
            self.assertEqual({row["scorable"] for row in rows}, {"excluded"})

            # A side that is not ready excludes all of them.
            rows = self._six_ready(binary)
            rows[2]["ready"] = "no"
            rows = apply_monorepo_gate(rows, _all_smoke(), PARITY_OK)
            self.assertEqual({row["scorable"] for row in rows}, {"excluded"})
            self.assertIn("53166 without not ready", rows[0]["_scorable_reason"])

    def test_sides_must_bundle_the_same_provider(self):
        from thesis.ab.step8_pin_dry_run import assess_monorepo_row, check_pr_providers

        with tempfile.TemporaryDirectory() as tmp:
            binary = make_exec(Path(tmp) / "opencode")
            other = dict(self.provider, tree="b" * 40)
            rows = [
                assess_monorepo_row({"pr": "51062", "side": "with", "sha": SHA_WITH}, layout="monorepo",
                                    provider=self.provider, binary=binary, loaded_source="none"),
                assess_monorepo_row({"pr": "51062", "side": "without", "sha": SHA_WITHOUT}, layout="monorepo",
                                    provider=other, binary=binary, loaded_source="none"),
            ]
            check_pr_providers(rows)
            for row in rows:
                self.assertEqual(row["ready"], "no")
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

    def test_monorepo_table_is_separate_and_keyed_by_side(self):
        from thesis.ab import step8_pin_dry_run as dry
        from thesis.ab.step8_monorepo_build import write_records

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
            out.write_text("untouched\n")
            bin_root = tmp / "src"
            make_monorepo(bin_root / "worktrees" / SHA_WITH)
            make_monorepo(bin_root / "worktrees" / SHA_WITHOUT)
            binary = make_exec(dry.binary_path(bin_root, SHA_WITH))
            builds = tmp / "monorepo-builds.csv"
            write_records(_good_records(binary, SHA_WITH), builds)
            with patch.object(dry, "trace_binary", return_value=("", "none")):
                gated = dry.run_monorepo(
                    [{"pr": "51062", "side": "with", "sha": SHA_WITH}], cache=tmp / "cache",
                    bin_root=bin_root, mirror=None, smoke_csv=tmp / "no-smoke.csv",
                    builds_csv=tmp / "no-builds.csv", parity_csv=tmp / "no-parity.csv",
                )
            self.assertEqual(gated[0]["ready"], "no")
            self.assertIn("build gate: control step not run", gated[0]["reason"])
            mono_out = tmp / "dry-run-monorepo.csv"
            with patch.object(dry, "trace_binary", return_value=("", "none")) as traced:
                rows = dry.refresh_monorepo(pins, rerun, mono_out, cache=tmp / "cache", bin_root=bin_root,
                                            mirror=None, smoke_csv=tmp / "no-smoke.csv", builds_csv=builds,
                                            parity_csv=tmp / "no-parity.csv")
            self.assertEqual(traced.call_count, 1)
            self.assertEqual(out.read_text(), "untouched\n")
            written = _rows(mono_out)
            self.assertEqual(list(written[0].keys()), dry.MONOREPO_FIELDS)
            self.assertEqual([row["side_key"] for row in written], ["51062:with", "51062:without"])
            with_row, without_row = written
            self.assertEqual((with_row["ready"], with_row["loaded_source"]), ("yes", "bundled"))
            self.assertEqual((without_row["ready"], with_row["scorable"]), ("no", "excluded"))
            self.assertEqual(with_row["scoring_parity"], "fail")
            self.assertIn("scoring parity not run", rows[0]["_scorable_reason"])
            self.assertIn("monorepo sides 2 ready 1 scorable 0", dry.summarize_monorepo(rows))
            with self.assertRaises(SystemExit):
                dry.write_monorepo_csv([rows[0], rows[0]], tmp / "dup.csv")

    def test_full_dry_run_keeps_main_format(self):
        from thesis.ab import step8_pin_dry_run as dry

        self.assertEqual(dry.MONOREPO_FIELDS[0], "side_key")
        self.assertEqual(dry.MONOREPO_FIELDS[1: len(dry.FIELDS) + 1], dry.FIELDS)
        for name in ("provider_mode", "bundled_provider", "scoring_parity", "scorable"):
            self.assertNotIn(name, dry.FIELDS)
            self.assertIn(name, dry.MONOREPO_FIELDS)
        self.assertEqual(list(_rows(DEFAULT_OUT / "dry-run.csv")[0].keys()), dry.FIELDS)
        self.assertEqual(dry.DEFAULT_MONOREPO_OUT.name, "dry-run-monorepo.csv")
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            out = tmp / "dry-run.csv"
            with patch.object(dry, "seed_versions", return_value={}), \
                    patch.object(dry, "trace_binary", return_value=("", "none")):
                rows = dry.run_dry(DEFAULT_OUT / "pins.csv", DEFAULT_OUT / "rerun-1443.json", tmp / "cache",
                                   tmp / "src", "bun", out)
            written = _rows(out)
            self.assertEqual(list(written[0].keys()), dry.FIELDS)
            deferred = [row for row in written if row["pr"] in monorepo.MONOREPO_PRS]
            self.assertEqual(len(deferred), 6)
            self.assertTrue(all(row["reason"].startswith("deferred") for row in deferred))
            self.assertEqual(len(rows), 594)

    def test_committed_tables(self):
        # Main's dry-run table from #160 is not rewritten: the six rows stay deferred there.
        main_dry = _rows(DEFAULT_OUT / "dry-run.csv")
        self.assertNotIn("provider_mode", main_dry[0])
        main_mono = [row for row in main_dry if row["pr"] in monorepo.MONOREPO_PRS]
        self.assertEqual(len(main_mono), 6)
        self.assertTrue(all(row["reason"].startswith("deferred") for row in main_mono))
        self.assertFalse((DEFAULT_OUT / "monorepo-dry-run.csv").exists())
        mono = _rows(DEFAULT_OUT / "dry-run-monorepo.csv")
        self.assertEqual(len(mono), 6)
        self.assertEqual(sorted(row["side_key"] for row in mono),
                         sorted(f"{row['pr']}:{row['side']}" for row in main_mono))
        self.assertEqual({row["sha"] for row in mono}, {row["sha"] for row in main_mono})
        for row in mono:
            self.assertEqual(row["group"], "monorepo")
            self.assertEqual(row["provider_mode"], "bundled")
            self.assertTrue(row["bundled_provider"].startswith("@opencode/ai@2.0.2"))
            self.assertNotIn("deferred", row["reason"])
            self.assertTrue(row["reason"] or row["ready"] == "yes")
            # Parity passes on main's box data; no smoke is committed, so all are excluded.
            self.assertEqual(row["scoring_parity"], "pass")
            self.assertEqual(row["scorable"], "excluded")
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

    def test_assess_side(self):
        from thesis.ab.step8_monorepo_smoke import assess_side

        side = {"pr": "51062", "side": "with", "sha": SHA_WITH}
        clean = assess_side(side, "misleading-error", self._cell())
        self.assertEqual((clean["provider_faults"], clean["call"], clean["smoke_ok"]), (0, "solved", "yes"))
        faulted = assess_side(side, "misleading-error", self._cell(
            failure_class="infra", success=False, error="AI_APICallError: overloaded_error",
        ))
        self.assertEqual((faulted["provider_faults"], faulted["smoke_ok"]), (1, "no"))
        timeout = assess_side(side, "misleading-error", self._cell(
            failure_class="hang", success=False, error="TimeoutError timed out. stream error",
        ))
        self.assertEqual((timeout["provider_faults"], timeout["smoke_ok"]), (0, "yes"))
        unbundled = assess_side(side, "misleading-error", self._cell(provider_loaded_source=""))
        self.assertEqual(unbundled["smoke_ok"], "no")
        missing = assess_side(side, "misleading-error", None)
        self.assertEqual((missing["cell_present"], missing["smoke_ok"]), ("no", "no"))

    def test_smoke_side_ok_rechecks_counts(self):
        from thesis.ab.step8_monorepo_smoke import smoke_side_ok

        self.assertEqual(smoke_side_ok(None), (False, "smoke not run"))
        self.assertTrue(smoke_side_ok(_smoke_row("51062", "with"))[0])
        self.assertFalse(smoke_side_ok(_smoke_row("51062", "with", faults=2, smoke_ok="yes"))[0])
        self.assertFalse(smoke_side_ok(_smoke_row("51062", "with", loaded="separate_install"))[0])
        self.assertFalse(smoke_side_ok(_smoke_row("51062", "with", present="no"))[0])

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

            for side in sides:
                task = tasks[side["pr"]]
                _write(smoke._cell_path(out, side["pr"], side["side"], task, 1),
                       json.dumps(self._cell(task=task)))
            rows = smoke.collect(out, sides, tasks, PARITY_OK)
            self.assertEqual({row["scorable"] for row in rows}, {"yes"})
            self.assertEqual({row["scoring_parity"] for row in rows}, {"pass"})
            self.assertIn("scoring_parity pass -> yes", smoke.summarize(rows))

            rows = smoke.collect(out, sides, tasks, (False, "scoring parity 6/7 cells"))
            self.assertEqual({row["scorable"] for row in rows}, {"excluded"})

            # One faulted cell (written to the side JSONL) excludes all six.
            smoke._cell_path(out, "51062", "without", "misleading-error", 1).unlink()
            _write(out / "51062" / "without.jsonl", json.dumps(self._cell(
                failure_class="infra", success=False, error="Unhandled chunk type: foo",
            )) + "\n")
            rows = smoke.collect(out, sides, tasks, PARITY_OK)
            by_key = {(row["pr"], row["side"]): row for row in rows}
            self.assertEqual(by_key[("51062", "without")]["provider_faults"], 1)
            self.assertEqual({row["scorable"] for row in rows}, {"excluded"})
            self.assertIn("51062 without: smoke shows 1 provider fault", by_key[("53166", "with")]["reason"])
            report = Path(tmp) / "monorepo-smoke.csv"
            smoke.write_report(rows, report)
            loaded = smoke.load_smoke(report)
            self.assertEqual(list(next(iter(loaded.values())).keys()), smoke.FIELDS)
            self.assertFalse(smoke.group_decision(loaded, sides, PARITY_OK)[0])

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
