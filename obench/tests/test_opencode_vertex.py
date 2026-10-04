#!/usr/bin/env python3
"""Vertex Opus routing and non-interactive flags for old OpenCode binaries."""

import importlib.util
import json
import os
import stat
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

ADAPTERS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "adapters")

HELP_MODERN = textwrap.dedent("""\
    -m, --model
    --variant
    --auto
    --dangerously-skip-permissions
    --format
    --dir
    --title
""")

HELP_SKIP = textwrap.dedent("""\
    -m, --model
    --variant
    --dangerously-skip-permissions
    --format
    --dir
    --title
""")

HELP_BARE = "-m, --model\n"

FAKE = textwrap.dedent("""\
    #!/usr/bin/env python3
    import json, os, sys, time
    args = sys.argv[1:]
    if args == ["--version"]:
        print("vertex-test")
        raise SystemExit(0)
    if args[:2] == ["run", "--help"]:
        sys.stdout.write(os.environ.get("FAKE_HELP", ""))
        raise SystemExit(0)
    if args[:1] == ["models"]:
        if "--print-logs" in args:
            sys.stdout.write(os.environ.get("FAKE_PERM", "ok"))
        else:
            sys.stdout.write(os.environ.get("FAKE_MODELS", ""))
        raise SystemExit(0)
    if os.environ.get("FAKE_PROMPT") == "1":
        print("Do you want to allow this?", flush=True)
        time.sleep(120)
        raise SystemExit(0)
    if "--print-logs" in args and "FAKE_PROBE" in os.environ:
        sys.stdout.write(os.environ.get("FAKE_PROBE", ""))
        raise SystemExit(int(os.environ.get("FAKE_PROBE_CODE", "1")))
    dump = os.environ.get("FAKE_DUMP")
    if dump:
        payload = {
            "argv": args,
            "anthropic": os.environ.get("ANTHROPIC_API_KEY"),
            "openai": os.environ.get("OPENAI_API_KEY"),
            "creds": os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"),
            "project": os.environ.get("GOOGLE_CLOUD_PROJECT"),
            "location": os.environ.get("VERTEX_LOCATION"),
        }
        cfg = os.environ.get("OPENCODE_CONFIG")
        if cfg and os.path.isfile(cfg):
            payload["config"] = open(cfg, encoding="utf-8").read()
        with open(dump, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
    tokens = {"input": 11, "output": 7, "reasoning": 5, "cache": {"read": 13, "write": 17}, "total": 53}
    print(json.dumps({"type": "step_finish", "part": {"tokens": tokens}}))
""")


def load_opencode():
    spec = importlib.util.spec_from_file_location(
        "opencode_vertex_adapter", os.path.join(ADAPTERS_DIR, "opencode.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class EnvPatch:
    def __enter__(self):
        self.saved = dict(os.environ)
        return os.environ

    def __exit__(self, *exc):
        os.environ.clear()
        os.environ.update(self.saved)


def write_fake(directory: Path) -> Path:
    path = directory / "opencode"
    path.write_text(FAKE, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


class TestVertexFlags(unittest.TestCase):
    def setUp(self):
        self.openc = load_opencode()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.binary = write_fake(Path(self.tmp.name))
        self.dump = Path(self.tmp.name) / "dump.json"
        self.work = Path(self.tmp.name) / "work"
        self.work.mkdir()

    def _run(self, help_text, extra=None):
        with EnvPatch() as env:
            env["OBENCH_OPENCODE_BIN"] = str(self.binary)
            env["FAKE_HELP"] = help_text
            env["FAKE_DUMP"] = str(self.dump)
            env["ANTHROPIC_API_KEY"] = "sk-ant-test"
            env["OPENAI_API_KEY"] = "sk-openai-test"
            env["GOOGLE_APPLICATION_CREDENTIALS"] = "/tmp/adc.json"
            env["GOOGLE_CLOUD_PROJECT"] = "proj"
            env.pop("VERTEX_LOCATION", None)
            env.pop("OBENCH_OPENCODE_CONFIG_JSON", None)
            env.pop("OBENCH_OPENCODE_PERMISSION_CONFIG", None)
            if extra:
                env.update(extra)
            return self.openc.run("ping", str(self.work), "claude-opus-5-5", 30)

    def _dump(self):
        return json.loads(self.dump.read_text(encoding="utf-8"))

    def test_vertex_command_keeps_google_adc_and_uses_auto(self):
        res = self._run(HELP_MODERN)
        self.assertTrue(res["completed"], res.get("error"))
        cmd = res["cmd"]
        self.assertEqual(cmd[cmd.index("-m") + 1], "google-vertex-anthropic/claude-opus-5-5@default")
        self.assertEqual(cmd[cmd.index("--variant") + 1], "medium")
        self.assertIn("--auto", cmd)
        self.assertNotIn("--dangerously-skip-permissions", cmd)
        dumped = self._dump()
        self.assertEqual(dumped["anthropic"], "sk-ant-test")
        self.assertIsNone(dumped["openai"])
        self.assertEqual(dumped["creds"], "/tmp/adc.json")
        self.assertEqual(dumped["project"], "proj")
        self.assertEqual(dumped["location"], "global")
        self.assertEqual(res["tokens_input_uncached"], 11)
        self.assertEqual(res["tokens_output"], 12)
        self.assertEqual(res["tokens_cache_read"], 13)
        self.assertEqual(res["tokens_cache_write"], 17)

    def test_skip_flag_when_auto_is_absent(self):
        res = self._run(HELP_SKIP)
        self.assertTrue(res["completed"], res.get("error"))
        cmd = res["cmd"]
        self.assertIn("--dangerously-skip-permissions", cmd)
        self.assertNotIn("--auto", cmd)
        self.assertEqual(cmd[cmd.index("--variant") + 1], "medium")

    def test_no_skip_flag_writes_provider_and_allow_permissions(self):
        from thesis.ab.compat import vertex_provider_config
        res = self._run(HELP_BARE, {
            "OBENCH_OPENCODE_CONFIG_JSON": json.dumps(vertex_provider_config()),
        })
        self.assertTrue(res["completed"], res.get("error"))
        cmd = res["cmd"]
        self.assertNotIn("--auto", cmd)
        self.assertNotIn("--dangerously-skip-permissions", cmd)
        body = json.loads(self._dump()["config"])
        provider = body["provider"]["google-vertex-anthropic"]
        self.assertEqual(provider["npm"], "@ai-sdk/google-vertex/anthropic")
        limits = provider["models"]["claude-opus-5-5@default"]["limit"]
        self.assertEqual(limits, {"context": 1000000, "output": 128000})
        for key in ("edit", "bash", "webfetch", "websearch", "read", "write"):
            self.assertEqual(body["permission"][key], "allow")

    def test_permission_config_off_omits_permission_key(self):
        from thesis.ab.compat import vertex_provider_config
        res = self._run(HELP_BARE, {
            "OBENCH_OPENCODE_CONFIG_JSON": json.dumps(vertex_provider_config()),
            "OBENCH_OPENCODE_PERMISSION_CONFIG": "0",
        })
        self.assertTrue(res["completed"], res.get("error"))
        body = json.loads(self._dump()["config"])
        self.assertNotIn("permission", body)
        self.assertIn("google-vertex-anthropic", body["provider"])

    def test_prompt_fails_fast(self):
        started = time.monotonic()
        res = self._run(HELP_BARE, {"FAKE_PROMPT": "1"})
        elapsed = time.monotonic() - started
        self.assertFalse(res["completed"])
        self.assertEqual(res["error"], "waiting on a permission prompt")
        self.assertLess(elapsed, 20)


class TestAssessment(unittest.TestCase):
    def test_permission_args_prefer_auto(self):
        from thesis.ab.compat import permission_args
        self.assertEqual(permission_args(HELP_MODERN), ["--auto"])
        self.assertEqual(permission_args(HELP_SKIP), ["--dangerously-skip-permissions"])
        self.assertEqual(permission_args(HELP_BARE), [])

    def _binary(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return write_fake(Path(tmp.name))

    def test_provider_init_error_is_incompatible(self):
        from thesis.ab.compat import assess
        binary = self._binary()
        with EnvPatch() as env:
            env["FAKE_HELP"] = HELP_BARE
            env["FAKE_MODELS"] = ""
            env["FAKE_PERM"] = "ok"
            env["FAKE_PROBE"] = "ProviderInitError BunInstallFailedError"
            env["FAKE_PROBE_CODE"] = "1"
            result = assess(str(binary))
        self.assertEqual(result.status, "incompatible")
        self.assertIn("ProviderInitError", result.reason)
        self.assertEqual(result.config, {})

    def test_missing_model_is_configured_with_limits(self):
        from thesis.ab.compat import assess
        binary = self._binary()
        with EnvPatch() as env:
            env["FAKE_HELP"] = HELP_BARE
            env["FAKE_MODELS"] = ""
            env["FAKE_PERM"] = "ok"
            env.pop("FAKE_PROBE", None)
            result = assess(str(binary))
        self.assertEqual(result.status, "configured")
        limits = result.config["provider"]["google-vertex-anthropic"]["models"]["claude-opus-5-5@default"]["limit"]
        self.assertEqual(limits, {"context": 1000000, "output": 128000})
        self.assertEqual(result.config["permission"]["bash"], "allow")
        self.assertTrue(result.permission_config)

    def test_strict_schema_does_not_request_permission_config(self):
        from thesis.ab.compat import assess
        binary = self._binary()
        with EnvPatch() as env:
            env["FAKE_HELP"] = HELP_BARE
            env["FAKE_MODELS"] = ""
            env["FAKE_PERM"] = "ConfigInvalidError Unrecognized key: 'permission'"
            env.pop("FAKE_PROBE", None)
            result = assess(str(binary))
        self.assertEqual(result.status, "configured")
        self.assertNotIn("permission", result.config)
        self.assertFalse(result.permission_config)

    def test_listed_model_is_native(self):
        from thesis.ab.compat import MODEL_ID, assess
        binary = self._binary()
        with EnvPatch() as env:
            env["FAKE_HELP"] = HELP_MODERN
            env["FAKE_MODELS"] = MODEL_ID + "\n"
            env.pop("FAKE_PROBE", None)
            result = assess(str(binary))
        self.assertEqual(result.status, "native")
        self.assertEqual(result.config, {})
        self.assertFalse(result.permission_config)


if __name__ == "__main__":
    unittest.main()
