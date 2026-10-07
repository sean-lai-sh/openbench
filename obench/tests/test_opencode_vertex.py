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
            "base_url": os.environ.get("ANTHROPIC_BASE_URL"),
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

    def test_proxy_route_uses_the_anthropic_model_and_dummy_key(self):
        res = self._run(HELP_MODERN, {
            "OBENCH_OPENCODE_PROXY": json.dumps({
                "model_ref": "anthropic/claude-opus-5-5",
                "api_key": "proxy",
                "base_url": "http://127.0.0.1:9",
                "base_url_env": True,
            }),
        })
        self.assertTrue(res["completed"], res.get("error"))
        cmd = res["cmd"]
        self.assertEqual(cmd[cmd.index("-m") + 1], "anthropic/claude-opus-5-5")
        dumped = self._dump()
        self.assertEqual(dumped["anthropic"], "proxy")
        self.assertEqual(dumped["base_url"], "http://127.0.0.1:9")
        self.assertIsNone(dumped["location"])

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

    def test_proxy_route_keeps_provider_options_when_the_model_is_listed(self):
        from thesis.ab.compat import PROXY_MODEL_REF, assess
        binary = self._binary()
        with EnvPatch() as env:
            env["FAKE_HELP"] = HELP_MODERN
            env["FAKE_MODELS"] = PROXY_MODEL_REF + "\n"
            env["FAKE_PERM"] = "ok"
            result = assess(str(binary), route="proxy", proxy_url="http://127.0.0.1:9")
        self.assertEqual(result.status, "configured")
        provider = result.config["provider"]["anthropic"]
        self.assertEqual(provider["options"]["baseURL"], "http://127.0.0.1:9/v1")
        self.assertEqual(provider["models"]["claude-opus-5-5"]["limit"], {"context": 1000000, "output": 128000})
        self.assertEqual(result.proxy["model_ref"], PROXY_MODEL_REF)
        self.assertFalse(result.proxy["base_url_env"])

    def test_proxy_route_falls_back_to_the_base_url_env(self):
        from thesis.ab.compat import assess
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "opencode"
        path.write_text(textwrap.dedent("""\
            #!/usr/bin/env python3
            import os, sys
            args = sys.argv[1:]
            if args[:2] == ["run", "--help"]:
                sys.stdout.write("-m, --model\\n")
                raise SystemExit(0)
            if args[:1] == ["models"] and "--print-logs" in args:
                sys.stdout.write("ok")
                raise SystemExit(0)
            if args[:1] == ["models"]:
                cfg = os.environ.get("OPENCODE_CONFIG", "")
                body = open(cfg, encoding="utf-8").read() if cfg and os.path.isfile(cfg) else ""
                if "baseURL" in body:
                    sys.stdout.write("ConfigInvalidError Unrecognized key: 'api'")
                elif os.environ.get("ANTHROPIC_BASE_URL"):
                    sys.stdout.write("anthropic/claude-opus-5-5\\n")
                raise SystemExit(0)
        """), encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
        with EnvPatch() as env:
            env["FAKE_HELP"] = HELP_MODERN
            result = assess(str(path), route="proxy", proxy_url="http://127.0.0.1:9")
        self.assertEqual(result.status, "configured")
        self.assertNotIn("options", result.config["provider"]["anthropic"])
        self.assertTrue(result.proxy["base_url_env"])
        self.assertEqual(result.proxy["base_url"], "http://127.0.0.1:9/v1")

    def test_proxy_route_is_incompatible_when_the_model_is_absent(self):
        from thesis.ab.compat import assess
        binary = self._binary()
        with EnvPatch() as env:
            env["FAKE_HELP"] = HELP_BARE
            env["FAKE_MODELS"] = ""
            env["FAKE_PERM"] = "ok"
            result = assess(str(binary), route="proxy", proxy_url="http://127.0.0.1:9")
        self.assertEqual(result.status, "incompatible")
        self.assertIn("anthropic/claude-opus-5-5", result.reason)
        self.assertEqual(result.config, {})

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


class TestProviderSdkPin(unittest.TestCase):
    def test_install_uses_the_pin_and_an_absolute_bun(self):
        import obench.adapters.opencode as opencode
        origin = Path.cwd()
        repo = Path(tempfile.mkdtemp())
        os.chdir(repo)
        self.addCleanup(os.chdir, origin)
        args_file = repo / "args.txt"
        bun = repo / "results" / "opencode-src" / "bun" / "1.2.14" / "bun"
        bun.parent.mkdir(parents=True)
        bun.write_text(textwrap.dedent("""\
            #!/usr/bin/env python3
            import os, pathlib, sys
            args = sys.argv[1:]
            dest = pathlib.Path(os.environ["BUN_ARGS"])
            previous = dest.read_text(encoding="utf-8") if dest.is_file() else ""
            dest.write_text(previous + "\\n".join(args) + "\\n", encoding="utf-8")
            for arg in args:
                if arg.startswith("@ai-sdk/anthropic@"):
                    version = arg.rsplit("@", 1)[1]
                    module = pathlib.Path(os.environ["XDG_CACHE_HOME"]) / "opencode" / "node_modules" / "@ai-sdk" / "anthropic" / "package.json"
                    module.parent.mkdir(parents=True, exist_ok=True)
                    module.write_text('{"version": "%s"}' % version, encoding="utf-8")
        """), encoding="utf-8")
        bun.chmod(0o755)
        home = Path(tempfile.mkdtemp())
        env = os.environ.copy()
        env["XDG_CACHE_HOME"] = str(home)
        env["BUN_ARGS"] = str(args_file)
        proxy = {
            "needs_sdk": True,
            "bun": "results/opencode-src/bun/1.2.14/bun",
            "anthropic_sdk": "1.2.12",
            "cache_version": "1",
        }
        self.assertEqual(opencode._ensure_provider_sdk(env, proxy), "1.2.12")
        self.assertEqual(opencode._ensure_provider_sdk(env, proxy), "1.2.12")
        self.assertEqual(env["OPENCODE_DISABLE_DEFAULT_PLUGINS"], "1")
        self.assertEqual((home / "opencode" / "version").read_text(encoding="utf-8"), "1")
        self.assertEqual(
            args_file.read_text(encoding="utf-8").splitlines(),
            ["add", "@ai-sdk/anthropic@1.2.12"],
        )
        saved = json.loads((home / "opencode" / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["dependencies"]["@ai-sdk/anthropic"], "latest")
        installed = json.loads(
            (home / "opencode" / "node_modules" / "@ai-sdk" / "anthropic" / "package.json").read_text(encoding="utf-8")
        )
        self.assertEqual(installed["version"], "1.2.12")

    def test_beta_install_alias_keeps_the_pin(self):
        import obench.adapters.opencode as opencode
        origin = Path.cwd()
        repo = Path(tempfile.mkdtemp())
        os.chdir(repo)
        self.addCleanup(os.chdir, origin)
        args_file = repo / "args.txt"
        bun = repo / "results" / "opencode-src" / "bun" / "1.2.14" / "bun"
        bun.parent.mkdir(parents=True)
        bun.write_text(textwrap.dedent("""\
            #!/usr/bin/env python3
            import os, pathlib, sys
            args = sys.argv[1:]
            dest = pathlib.Path(os.environ["BUN_ARGS"])
            previous = dest.read_text(encoding="utf-8") if dest.is_file() else ""
            dest.write_text(previous + "\\n".join(args) + "\\n", encoding="utf-8")
            for arg in args:
                if arg.startswith("@ai-sdk/anthropic@"):
                    version = arg.rsplit("@", 1)[1]
                    module = pathlib.Path(os.environ["XDG_CACHE_HOME"]) / "opencode" / "node_modules" / "@ai-sdk" / "anthropic" / "package.json"
                    module.parent.mkdir(parents=True, exist_ok=True)
                    module.write_text('{"version": "%s"}' % version, encoding="utf-8")
        """), encoding="utf-8")
        bun.chmod(0o755)
        home = Path(tempfile.mkdtemp())
        env = os.environ.copy()
        env["XDG_CACHE_HOME"] = str(home)
        env["BUN_ARGS"] = str(args_file)
        proxy = {
            "needs_sdk": True,
            "bun": "results/opencode-src/bun/1.2.14/bun",
            "anthropic_sdk": "2.0.0-beta.11",
            "sdk_install_alias": "beta",
            "cache_version": "3",
        }
        self.assertEqual(opencode._ensure_provider_sdk(env, proxy), "2.0.0-beta.11")
        self.assertEqual(opencode._ensure_provider_sdk(env, proxy), "2.0.0-beta.11")
        self.assertEqual((home / "opencode" / "version").read_text(encoding="utf-8"), "3")
        self.assertEqual(env["OPENCODE_DISABLE_DEFAULT_PLUGINS"], "1")
        saved = json.loads((home / "opencode" / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["dependencies"]["@ai-sdk/anthropic"], "beta")
        installed = json.loads(
            (home / "opencode" / "node_modules" / "@ai-sdk" / "anthropic" / "package.json").read_text(encoding="utf-8")
        )
        self.assertEqual(installed["version"], "2.0.0-beta.11")

    def test_sdk_drift_names_the_installed_version(self):
        import obench.adapters.opencode as opencode
        home = Path(tempfile.mkdtemp())
        module = home / "opencode" / "node_modules" / "@ai-sdk" / "anthropic" / "package.json"
        module.parent.mkdir(parents=True)
        module.write_text('{"version": "4.0.72"}', encoding="utf-8")
        env = {"XDG_CACHE_HOME": str(home)}
        proxy = {"needs_sdk": True, "anthropic_sdk": "2.0.0"}
        self.assertEqual(
            opencode._provider_sdk_drift(env, proxy),
            "sdk drift: installed @ai-sdk/anthropic 4.0.72 != pin 2.0.0",
        )
        module.write_text('{"version": "2.0.0"}', encoding="utf-8")
        self.assertEqual(opencode._provider_sdk_drift(env, proxy), "")

    def test_print_logs_is_added_only_when_evidence_is_kept(self):
        import obench.adapters.opencode as opencode
        help_text = "\n".join([
            "--auto",
            "-m, --model",
            "--format",
            "--dir",
            "--title",
            "--print-logs",
        ])
        saved = os.environ.get("OBENCH_OPENCODE_EVIDENCE_DIR")
        try:
            os.environ.pop("OBENCH_OPENCODE_EVIDENCE_DIR", None)
            plain, _watched = opencode._build_cmd(
                "opencode", "anthropic/claude-opus-5-5", None, "/work", "ping", help_text,
            )
            self.assertNotIn("--print-logs", plain)
            os.environ["OBENCH_OPENCODE_EVIDENCE_DIR"] = "/tmp/evidence"
            logged, _watched = opencode._build_cmd(
                "opencode", "anthropic/claude-opus-5-5", None, "/work", "ping", help_text,
            )
            self.assertEqual(logged[2], "--print-logs")
            os.environ["OBENCH_OPENCODE_EVIDENCE_DIR"] = "/tmp/evidence"
            no_flag, _watched = opencode._build_cmd(
                "opencode", "anthropic/claude-opus-5-5", None, "/work", "ping",
                "--auto\n-m, --model\n",
            )
            self.assertNotIn("--print-logs", no_flag)
        finally:
            if saved is None:
                os.environ.pop("OBENCH_OPENCODE_EVIDENCE_DIR", None)
            else:
                os.environ["OBENCH_OPENCODE_EVIDENCE_DIR"] = saved

    def test_evidence_copy_keeps_each_storage_layout(self):
        import obench.adapters.opencode as opencode
        saved = os.environ.get("OBENCH_OPENCODE_EVIDENCE_DIR")
        try:
            modern_home = Path(tempfile.mkdtemp())
            modern = modern_home / "opencode"
            (modern / "storage" / "session").mkdir(parents=True)
            (modern / "storage" / "session" / "part.json").write_text(
                '{"tool":"read"}', encoding="utf-8",
            )
            (modern / "log").mkdir()
            (modern / "log" / "opencode.log").write_text("INFO service=session\n", encoding="utf-8")
            (modern / "opencode.db").write_bytes(b"sqlite-session")
            modern_dest = Path(tempfile.mkdtemp())
            os.environ["OBENCH_OPENCODE_EVIDENCE_DIR"] = str(modern_dest)
            opencode._preserve_opencode_evidence({"XDG_DATA_HOME": str(modern_home)})
            self.assertEqual(
                (modern_dest / "storage" / "session" / "part.json").read_text(encoding="utf-8"),
                '{"tool":"read"}',
            )
            self.assertIn(
                "service=session",
                (modern_dest / "log" / "opencode.log").read_text(encoding="utf-8"),
            )
            self.assertEqual((modern_dest / "opencode.db").read_bytes(), b"sqlite-session")
            self.assertFalse((modern_dest / "project").exists())

            old_home = Path(tempfile.mkdtemp())
            project = old_home / "opencode" / "project" / "proj123"
            (project / "storage" / "session").mkdir(parents=True)
            (project / "storage" / "session" / "part.json").write_text(
                '{"tool": "list"}', encoding="utf-8",
            )
            (project / "log").mkdir()
            (project / "log" / "dev.log").write_text("old-session\n", encoding="utf-8")
            old_dest = Path(tempfile.mkdtemp())
            os.environ["OBENCH_OPENCODE_EVIDENCE_DIR"] = str(old_dest)
            opencode._preserve_opencode_evidence({"XDG_DATA_HOME": str(old_home)})
            copied = old_dest / "project" / "proj123" / "storage" / "session" / "part.json"
            self.assertEqual(copied.read_text(encoding="utf-8"), '{"tool": "list"}')
            self.assertEqual(
                (old_dest / "project" / "proj123" / "log" / "dev.log").read_text(encoding="utf-8"),
                "old-session\n",
            )
            self.assertFalse((old_dest / "storage").exists())
        finally:
            if saved is None:
                os.environ.pop("OBENCH_OPENCODE_EVIDENCE_DIR", None)
            else:
                os.environ["OBENCH_OPENCODE_EVIDENCE_DIR"] = saved

    def test_exec_failure_is_infra_not_incompatible(self):
        from thesis.ab.compat import assess
        missing = Path(tempfile.mkdtemp()) / "opencode"
        result = assess(str(missing), route="proxy", proxy_url="http://127.0.0.1:9")
        self.assertEqual(result.status, "infra")
        self.assertIn("Errno", result.reason)
        self.assertNotIn("not listed", result.reason)


if __name__ == "__main__":
    unittest.main()
