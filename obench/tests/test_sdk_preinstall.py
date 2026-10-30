"""Pinned @ai-sdk/anthropic is pre-installed, seeded offline, and checked first.

Cells used to run ``bun add`` at start with ``check=False`` and only
compared the pin after the run, so H2 rows showed the package missing
(pins 2.0.77, 3.0.64, 2.0.0) or 4.0.87 against pin 2.0.0.
"""
import json
import os
import stat
import tempfile
import textwrap
import unittest
from pathlib import Path


def make_pin_root(root, version, installed=None):
    """A provisioned pin root holding ``version`` (or ``installed`` on disk)."""
    root = Path(root)
    pkg = root / version / "node_modules" / "@ai-sdk" / "anthropic"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "package.json").write_text(
        json.dumps({"name": "@ai-sdk/anthropic", "version": installed or version}),
        encoding="utf-8",
    )
    (pkg / "index.js").write_text("module.exports = {}\n", encoding="utf-8")
    for path in [*pkg.rglob("*"), pkg]:
        path.chmod(path.stat().st_mode & ~0o222)
    return root


def never_bun(root, marker):
    bun = Path(root) / "bun"
    bun.write_text(
        "#!/bin/sh\necho ran >> %s\n" % marker, encoding="utf-8",
    )
    bun.chmod(0o755)
    return bun


def _executable(path, body):
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


class CellStartTests(unittest.TestCase):
    def _run(self, pin_root, pre_installed=None):
        import obench.adapters.opencode as opencode

        root = Path(tempfile.mkdtemp())
        started = root / "started"
        marker = root / "bun-ran"
        binary = root / "opencode"
        _executable(binary, textwrap.dedent("""\
            #!/usr/bin/env python3
            import json, pathlib, sys
            args = sys.argv[1:]
            if args[:2] == ["run", "--help"]:
                print("--auto\\n-m, --model\\n--format\\n--dir\\n--title")
                raise SystemExit(0)
            pathlib.Path(STARTED).write_text("request", encoding="utf-8")
            print(json.dumps({"type": "step_finish", "part": {"tokens": {
                "input": 1, "output": 1, "reasoning": 0,
                "cache": {"read": 0, "write": 0}, "total": 2}}}))
        """).replace("STARTED", repr(str(started))))
        proxy = {
            "model_ref": "anthropic/claude-opus-5-5",
            "api_key": "proxy",
            "base_url": "http://127.0.0.1:9/v1",
            "anthropic_sdk": "2.0.0",
            "cache_version": "9",
            "bun": str(never_bun(root, marker)),
            "pin_root": str(pin_root),
        }
        keys = ("OBENCH_OPENCODE_BIN", "OBENCH_OPENCODE_PROXY",
                "OBENCH_OPENCODE_EVIDENCE_DIR", "XDG_CACHE_HOME_SEED")
        saved = {key: os.environ.get(key) for key in keys}
        work = root / "work"
        work.mkdir()
        real_isolated = opencode._isolated_env

        def isolated():
            env, home = real_isolated()
            if pre_installed:
                module = Path(env["XDG_CACHE_HOME"]) / "opencode" / "node_modules" / "@ai-sdk" / "anthropic"
                module.mkdir(parents=True, exist_ok=True)
                (module / "package.json").write_text(
                    json.dumps({"version": pre_installed}), encoding="utf-8")
            return env, home

        try:
            os.environ["OBENCH_OPENCODE_BIN"] = str(binary)
            os.environ["OBENCH_OPENCODE_PROXY"] = json.dumps(proxy)
            os.environ["OBENCH_OPENCODE_EVIDENCE_DIR"] = str(root / "evidence")
            opencode._isolated_env = isolated
            row = opencode.run("say hi", str(work), "claude-opus-5-5", 30)
        finally:
            opencode._isolated_env = real_isolated
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        return row, started.exists(), marker.exists()

    def test_present_pin_is_seeded_and_the_agent_runs(self):
        pins = make_pin_root(Path(tempfile.mkdtemp()), "2.0.0")
        row, requested, bun_ran = self._run(pins)
        self.assertTrue(requested)
        self.assertFalse(bun_ran)
        self.assertTrue(row["completed"])
        self.assertEqual(row["installed_anthropic"], "2.0.0")
        self.assertNotIn("sdk_drift", row)
        self.assertNotEqual(row.get("env_cause"), "provider_sdk_drift")

    def test_missing_pin_fails_fast_without_a_request(self):
        row, requested, bun_ran = self._run(Path(tempfile.mkdtemp()))
        self.assertFalse(requested)
        self.assertFalse(bun_ran)
        self.assertFalse(row["completed"])
        self.assertEqual(row["failure_class"], "infra")
        self.assertIs(row["env_failure"], True)
        self.assertEqual(row["env_cause"], "provider_sdk_drift")
        self.assertIn("missing != pin 2.0.0", row["error"])
        self.assertEqual(row["installed_anthropic"], "missing")
        self.assertIsNone(row["tokens"])

    def test_wrong_version_fails_fast_without_a_request(self):
        # Pin root mislabelled (4.0.87 under 2.0.0) is not copied; a cell
        # cache already on 4.0.87 is not overwritten into a pass either.
        pins = make_pin_root(Path(tempfile.mkdtemp()), "2.0.0", installed="4.0.87")
        row, requested, bun_ran = self._run(pins, pre_installed="4.0.87")
        self.assertFalse(requested)
        self.assertFalse(bun_ran)
        self.assertEqual(row["env_cause"], "provider_sdk_drift")
        self.assertIn("4.0.87 != pin 2.0.0", row["error"])
        self.assertEqual(row["installed_anthropic"], "4.0.87")

    def test_run_columns_record_the_installed_sdk_and_subclass(self):
        from obench.run import ROW_FIELDS as RESULT_COLUMNS
        self.assertIn("installed_anthropic", RESULT_COLUMNS)
        self.assertIn("failure_subclass", RESULT_COLUMNS)


class ProvisionTests(unittest.TestCase):
    def _bun(self, root, installs=None):
        bun = Path(root) / "bun"
        _executable(bun, textwrap.dedent("""\
            #!/usr/bin/env python3
            import json, pathlib, sys
            args = sys.argv[1:]
            cwd = pathlib.Path(args[args.index("--cwd") + 1])
            want = json.loads((cwd / "package.json").read_text())["dependencies"]["@ai-sdk/anthropic"]
            pkg = cwd / "node_modules" / "@ai-sdk" / "anthropic"
            pkg.mkdir(parents=True)
            (pkg / "package.json").write_text(json.dumps({"version": INSTALLS or want}))
        """).replace("INSTALLS", repr(installs)))
        return str(bun)

    def test_provision_writes_a_read_only_tree_and_manifest(self):
        from thesis.ab import provision_provider_pins as prov
        root = Path(tempfile.mkdtemp())
        pins = root / "pins"
        self.assertEqual(prov.main(["--root", str(pins), "--bun", self._bun(root), "2.0.0"]), 0)
        manifest = json.loads((pins / "2.0.0" / "manifest.json").read_text())
        self.assertEqual(manifest["version"], "2.0.0")
        self.assertIn("node_modules/@ai-sdk/anthropic/package.json", manifest["files"])
        self.assertEqual(prov.verify(pins, "2.0.0"), "")
        self.assertFalse(os.access(pins / "2.0.0" / "node_modules", os.W_OK) and os.geteuid() != 0)
        self.assertEqual(prov.main(["--root", str(pins), "--verify", "2.0.0"]), 0)

    def test_provision_refuses_a_resolved_latest(self):
        from thesis.ab import provision_provider_pins as prov
        root = Path(tempfile.mkdtemp())
        pins = root / "pins"
        self.assertEqual(
            prov.main(["--root", str(pins), "--bun", self._bun(root, "4.0.87"), "2.0.0"]), 1,
        )
        self.assertFalse((pins / "2.0.0").exists())

    def test_referenced_pins_cover_the_observed_drift(self):
        from thesis.ab import provision_provider_pins as prov
        pins = prov.referenced_pins()
        for version in ("2.0.77", "3.0.64", "2.0.0"):
            self.assertIn(version, pins)
        self.assertNotIn("latest", pins)


SIGNATURE_400 = (
    'AI_APICallError: messages.3.content.0: Invalid `signature` in `thinking` block '
    '{"type":"error","error":{"type":"invalid_request_error","message":'
    '"messages.3.content.0: Invalid `signature` in `thinking` block"}}'
)


class SignatureReplayTests(unittest.TestCase):
    def test_signature_400_is_a_scored_agent_fail(self):
        from obench.failure_class import classify_failure
        row = {"success": False, "completed": True, "provider_error": SIGNATURE_400,
               "output_tail": SIGNATURE_400}
        self.assertEqual(classify_failure(row, SIGNATURE_400), "wrong_answer")
        self.assertEqual(row["failure_subclass"], "thinking_signature_replay")

    def test_stored_infra_signature_row_is_scored(self):
        from obench.cell_columns import excluded_from_scoring, scoring_override_class
        row = {"success": False, "failure_class": "infra", "error": SIGNATURE_400}
        self.assertFalse(excluded_from_scoring(row))
        self.assertIsNone(scoring_override_class(row))
        flagged = dict(row, env_failure=True, env_cause="adapter_infra")
        self.assertFalse(excluded_from_scoring(flagged))

    def test_proven_mangling_or_other_env_cause_stays_unscored(self):
        from obench.cell_columns import excluded_from_scoring
        mangled = {"success": False, "failure_class": "infra", "error": SIGNATURE_400,
                   "request_mangled": True}
        self.assertTrue(excluded_from_scoring(mangled))
        timeout = {"success": False, "failure_class": "infra", "error": SIGNATURE_400,
                   "env_failure": True, "env_cause": "checker_timeout"}
        self.assertTrue(excluded_from_scoring(timeout))

    def test_other_infra_rows_stay_env_failures(self):
        from obench.cell_columns import excluded_from_scoring
        from obench.failure_class import classify_failure
        for text in ("AI_TypeValidationError: Unhandled chunk type: stream-start",
                     "sdk drift: installed @ai-sdk/anthropic 4.0.87 != pin 2.0.0",
                     'invalid_request_error: messages.1: "max_tokens" is too large'):
            row = {"success": False, "failure_class": "infra", "error": text}
            self.assertTrue(excluded_from_scoring(row), text)
            fresh = {"success": False, "provider_error": text}
            self.assertNotEqual(classify_failure(fresh, text), "wrong_answer", text)
            self.assertNotIn("failure_subclass", fresh)


if __name__ == "__main__":
    unittest.main()
