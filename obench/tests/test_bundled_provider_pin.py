"""Bundled --single binaries pin @ai-sdk/anthropic from the source commit.

The c436fc69 layout is the one that failed in the runner: packages/opencode
package.json depends on 3.0.71, and bun.lock's @ai-sdk/anthropic entry is
3.0.64 because another package depends on that version. The prebuilt
binary logs "using bundled provider" and embeds 3.0.71. The expected pin
is read from that commit, not from the worktree that happens to be checked
out and not from bun.lock.
"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


BUILD_TS = 'const singleFlag = process.argv.includes("--single")\n'
BUNDLED_PROVIDER_TS = (
    'log.info("using bundled provider", { pkg: "@ai-sdk/anthropic" })\n'
    'const BUNDLED_PROVIDERS = { "@ai-sdk/anthropic": createAnthropic }\n'
)
RUNTIME_PROVIDER_TS = 'const mod = await BunProc.install("@ai-sdk/anthropic", "latest")\n'
# 3.0.64 is the lockfile entry for packages/plugin, not packages/opencode.
OTHER_PACKAGE_LOCK = {
    "packages": {
        "packages/plugin": [
            "@opencode-ai/plugin@workspace:packages/plugin",
            "",
            {"dependencies": {"@ai-sdk/anthropic": "3.0.64"}},
            "sha-plugin",
        ],
        "@ai-sdk/anthropic": [
            "@ai-sdk/anthropic@3.0.64",
            "",
            {"dependencies": {"@ai-sdk/provider": "2.0.0"}},
            "sha-other",
        ],
    }
}


def _git(repo: Path, *args: str) -> str:
    env = os.environ.copy()
    env.update({
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    })
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.stdout.strip()


def _init(repo: Path) -> None:
    repo.mkdir(parents=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _root_package() -> str:
    return json.dumps({"packageManager": "bun@1.2.14"})


def _opencode_package(version: str) -> str:
    return json.dumps({"dependencies": {"@ai-sdk/anthropic": version}})


def _place(cache: Path, repo: Path, sha: str) -> Path:
    dest = cache / "worktrees" / sha
    dest.parent.mkdir(parents=True, exist_ok=True)
    repo.rename(dest)
    return dest


def _state() -> dict:
    return {
        "ok": True,
        "harness": "opencode",
        "proxy": {"needs_sdk": True, "model_ref": "anthropic/claude-opus-5-5"},
    }


class BundledProviderPinTests(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.pop("OBENCH_ANTHROPIC_PIN", None)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("OBENCH_ANTHROPIC_PIN", None)
        else:
            os.environ["OBENCH_ANTHROPIC_PIN"] = self._saved

    def _c436fc69_tree(self, cache: Path, *, checked_out_version: str, provider: str) -> tuple[Path, str]:
        """Source commit pins 3.0.71. HEAD is a different checkout."""
        repo = Path(tempfile.mkdtemp()) / "src"
        _init(repo)
        _write(repo / "package.json", _root_package())
        _write(repo / "bun.lock", json.dumps(OTHER_PACKAGE_LOCK))
        _write(repo / "packages/opencode/package.json", _opencode_package("3.0.71"))
        _write(repo / "packages/opencode/script/build.ts", BUILD_TS)
        _write(repo / "packages/opencode/src/provider/provider.ts", BUNDLED_PROVIDER_TS)
        sha = _commit(repo, "c436fc69 layout")
        _write(repo / "packages/opencode/package.json", _opencode_package(checked_out_version))
        _write(repo / "packages/opencode/src/provider/provider.ts", provider)
        _commit(repo, "checked out later")
        return _place(cache, repo, sha), sha

    def test_c436fc69_bundled_pin_comes_from_the_source_commit(self):
        from thesis.ab.provider_pin import apply_provider_pin
        from thesis.ab.run_ab import _decorate_toolchain
        from thesis.ab.sdk_pin import select_anthropic_pin
        from obench.adapters.opencode import _loaded_mismatch_text

        self.assertEqual(select_anthropic_pin(OTHER_PACKAGE_LOCK, registry={}), "3.0.64")
        cache = Path(tempfile.mkdtemp())
        checkout, sha = self._c436fc69_tree(
            cache, checked_out_version="9.9.9", provider=RUNTIME_PROVIDER_TS,
        )
        checked_out = json.loads((checkout / "packages/opencode/package.json").read_text())
        self.assertEqual(checked_out["dependencies"]["@ai-sdk/anthropic"], "9.9.9")
        state, err = _decorate_toolchain(_state(), cache, sha, "")
        self.assertIsNone(err)
        self.assertEqual(state["proxy"]["anthropic_sdk"], "3.0.71")
        self.assertEqual(state["proxy"]["pin_source"], "bundled_package_json")
        self.assertEqual(state["toolchain"]["anthropic"], "3.0.71")
        overlaid = apply_provider_pin(state["proxy"], cache, sha, "with", "825226")
        self.assertEqual(overlaid["provider_pins"], {"@ai-sdk/anthropic": "3.0.71"})
        self.assertEqual(overlaid["pin_source"], "bundled_package_json")
        self.assertEqual(_loaded_mismatch_text("3.0.71", "3.0.71", "embedded"), "")

    def test_bundled_loaded_mismatch_is_infra(self):
        from thesis.ab.run_ab import _decorate_toolchain
        from obench.adapters.opencode import _attach_loaded_mismatch, _loaded_mismatch_text

        cache = Path(tempfile.mkdtemp())
        _checkout, sha = self._c436fc69_tree(
            cache, checked_out_version="9.9.9", provider=RUNTIME_PROVIDER_TS,
        )
        state, err = _decorate_toolchain(_state(), cache, sha, "")
        self.assertIsNone(err)
        pin = state["proxy"]["anthropic_sdk"]
        mismatch = _loaded_mismatch_text(pin, "3.0.64", "embedded")
        self.assertEqual(mismatch, "provider_pin_mismatch: loaded 3.0.64 != pin 3.0.71")
        row = _attach_loaded_mismatch({"completed": True}, mismatch)
        self.assertEqual(row["failure_class"], "infra")
        self.assertFalse(row["completed"])
        self.assertIn("provider_pin_mismatch", row["error"])

    def test_non_bundled_build_still_uses_bun_lock(self):
        from thesis.ab.run_ab import _decorate_toolchain

        cache = Path(tempfile.mkdtemp())
        repo = Path(tempfile.mkdtemp()) / "src"
        _init(repo)
        _write(repo / "package.json", _root_package())
        _write(repo / "bun.lock", json.dumps(OTHER_PACKAGE_LOCK))
        _write(repo / "packages/opencode/package.json", _opencode_package("3.0.71"))
        _write(repo / "packages/opencode/script/build.ts", BUILD_TS)
        _write(repo / "packages/opencode/src/provider/provider.ts", RUNTIME_PROVIDER_TS)
        sha = _commit(repo, "runtime install")
        _place(cache, repo, sha)
        state, err = _decorate_toolchain(_state(), cache, sha, "")
        self.assertIsNone(err)
        self.assertEqual(state["proxy"]["anthropic_sdk"], "3.0.64")
        self.assertNotEqual(state["proxy"].get("pin_source"), "bundled_package_json")
        self.assertEqual(state["toolchain"]["anthropic"], "3.0.64")

    def test_bundled_commit_without_an_exact_dependency_fails(self):
        from thesis.ab.run_ab import _decorate_toolchain, _pin_stop

        cache = Path(tempfile.mkdtemp())
        repo = Path(tempfile.mkdtemp()) / "src"
        _init(repo)
        _write(repo / "package.json", _root_package())
        _write(repo / "bun.lock", json.dumps(OTHER_PACKAGE_LOCK))
        _write(repo / "packages/opencode/package.json", _opencode_package("^3.0.71"))
        _write(repo / "packages/opencode/script/build.ts", BUILD_TS)
        _write(repo / "packages/opencode/src/provider/provider.ts", BUNDLED_PROVIDER_TS)
        sha = _commit(repo, "range")
        _place(cache, repo, sha)
        state, err = _decorate_toolchain(_state(), cache, sha, "")
        self.assertIsNotNone(err)
        self.assertTrue(err.startswith("provider_pin_mismatch:"))
        self.assertIn("not an exact version", err)
        self.assertNotIn("anthropic_sdk", state["proxy"])
        stopped = _pin_stop(err, state.get("toolchain"))
        self.assertEqual(stopped["status"], "infra")
        self.assertFalse(stopped["ok"])

        missing = Path(tempfile.mkdtemp()) / "src"
        _init(missing)
        _write(missing / "package.json", _root_package())
        _write(missing / "bun.lock", json.dumps(OTHER_PACKAGE_LOCK))
        _write(missing / "packages/opencode/package.json", json.dumps({"dependencies": {}}))
        _write(missing / "packages/opencode/script/build.ts", BUILD_TS)
        _write(missing / "packages/opencode/src/provider/provider.ts", BUNDLED_PROVIDER_TS)
        missing_sha = _commit(missing, "no dependency")
        missing_cache = Path(tempfile.mkdtemp())
        _place(missing_cache, missing, missing_sha)
        _state_missing, missing_err = _decorate_toolchain(_state(), missing_cache, missing_sha, "")
        self.assertTrue(missing_err.startswith("provider_pin_mismatch:"))
        self.assertIn("has no @ai-sdk/anthropic", missing_err)
        self.assertNotIn("anthropic_sdk", _state_missing["proxy"])
        self.assertEqual(_pin_stop(missing_err, {})["status"], "infra")


if __name__ == "__main__":
    unittest.main()
