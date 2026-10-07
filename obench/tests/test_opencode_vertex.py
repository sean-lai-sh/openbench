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
    log = os.environ.get("FAKE_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(args) + "\\n")
    exit_code = os.environ.get("FAKE_EXIT_CODE")
    if exit_code:
        raise SystemExit(int(exit_code))
    session = os.environ.get("FAKE_SESSION", "")
    if session:
        print(json.dumps({"type": "session", "sessionID": session}))
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
        agents = os.path.join(os.environ.get("XDG_CONFIG_HOME", ""), "opencode", "AGENTS.md")
        if os.path.isfile(agents):
            payload["agents"] = open(agents, encoding="utf-8").read()
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

    def _run(self, help_text, extra=None, instruction="ping"):
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
            env.pop("OBENCH_OPENCODE_MODE", None)
            env.pop("OBENCH_OPENCODE_PERMISSIONS", None)
            env.pop("OBENCH_OPENCODE_GLOBAL_AGENTS", None)
            env.pop("OBENCH_OPENCODE_LSP", None)
            env.pop("OBENCH_OPENCODE_BUN", None)
            env.pop("OBENCH_OPENCODE_WEBFETCH_URL", None)
            env.pop("OBENCH_OPENCODE_DISABLE_TOOLS", None)
            if extra:
                env.update(extra)
            return self.openc.run(instruction, str(self.work), "claude-opus-5-5", 30)

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

    def test_disable_tools_writes_mode_build_and_not_permission(self):
        res = self._run(HELP_BARE + "\n--mode\n", {
            "OBENCH_OPENCODE_MODE": "build",
            "OBENCH_OPENCODE_DISABLE_TOOLS": "bash,write",
            "OBENCH_OPENCODE_PERMISSION_CONFIG": "0",
            "OBENCH_OPENCODE_CONFIG_JSON": json.dumps({
                "provider": {"anthropic": {"name": "Anthropic"}},
            }),
        })
        self.assertTrue(res["completed"], res.get("error"))
        self.assertEqual(res["cmd"][res["cmd"].index("--mode") + 1], "build")
        body = json.loads(self._dump()["config"])
        self.assertEqual(body["mode"]["build"]["tools"], {"bash": False, "write": False})
        self.assertNotIn("permission", body)
        self.assertEqual(body["provider"]["anthropic"]["name"], "Anthropic")

    def test_mode_is_passed_when_the_binary_lists_it(self):
        help_text = HELP_MODERN + "--mode\n"
        res = self._run(help_text, {"OBENCH_OPENCODE_MODE": "plan"})
        self.assertTrue(res["completed"], res.get("error"))
        cmd = res["cmd"]
        self.assertEqual(cmd[cmd.index("--mode") + 1], "plan")
        self.assertIn("--auto", cmd)

    def test_mode_is_omitted_when_help_has_no_mode_flag(self):
        res = self._run(HELP_MODERN, {"OBENCH_OPENCODE_MODE": "plan"})
        self.assertTrue(res["completed"], res.get("error"))
        self.assertNotIn("--mode", res["cmd"])

    def test_empty_help_still_passes_mode(self):
        res = self._run("", {"OBENCH_OPENCODE_MODE": "plan"})
        self.assertTrue(res["completed"], res.get("error"))
        self.assertEqual(res["cmd"][res["cmd"].index("--mode") + 1], "plan")

    def test_workspace_permissions_drop_skip_flags_and_external_directory(self):
        res = self._run("", {
            "OBENCH_OPENCODE_PERMISSIONS": "workspace",
            "OBENCH_OPENCODE_PERMISSION_CONFIG": "0",
        })
        self.assertTrue(res["completed"], res.get("error"))
        cmd = res["cmd"]
        self.assertNotIn("--auto", cmd)
        self.assertNotIn("--dangerously-skip-permissions", cmd)
        body = json.loads(self._dump()["config"])
        self.assertEqual(body["permission"]["edit"], "allow")
        self.assertNotIn("external_directory", body["permission"])

    def test_global_agents_file_is_written_into_the_config_home(self):
        res = self._run(HELP_MODERN, {"OBENCH_OPENCODE_GLOBAL_AGENTS": "1"})
        self.assertTrue(res["completed"], res.get("error"))
        self.assertEqual(
            self._dump()["agents"],
            "Prefix every final answer with GLOBAL-RULE.\n",
        )

    def test_webfetch_placeholder_becomes_the_local_url(self):
        url = "http://127.0.0.1:9/color.png"
        res = self._run(
            HELP_MODERN,
            {"OBENCH_OPENCODE_WEBFETCH_URL": url},
            instruction="Use webfetch on __OBENCH_WEBFETCH_URL__ and write the colour.",
        )
        self.assertTrue(res["completed"], res.get("error"))
        prompt = res["cmd"][-1]
        self.assertIn(url, prompt)
        self.assertNotIn("__OBENCH_WEBFETCH_URL__", prompt)
        self.assertEqual(self.openc._WEBFETCH_PLACEHOLDER, "__OBENCH_WEBFETCH_URL__")

    def test_two_turns_continue_the_session_and_hide_the_markers(self):
        log = Path(self.tmp.name) / "calls.jsonl"
        help_text = HELP_MODERN + "--session\n--continue\n"
        instruction = (
            "turn one\n"
            "__OBENCH_USER_TURN__\n"
            "turn two\n"
            "__OBENCH_SINGLE_TURN__\n"
            "single fallback\n"
        )
        res = self._run(help_text, {
            "FAKE_LOG": str(log),
            "FAKE_SESSION": "ses_from_first",
        }, instruction=instruction)
        self.assertTrue(res["completed"], res.get("error"))
        calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(calls), 2)
        self.assertIn("turn one", calls[0])
        self.assertNotIn("turn two", calls[0])
        self.assertNotIn("__OBENCH_USER_TURN__", " ".join(calls[0]))
        self.assertIn("--session", calls[1])
        self.assertIn("ses_from_first", calls[1])
        self.assertIn("turn two", calls[1])
        self.assertNotIn("__OBENCH_SINGLE_TURN__", " ".join(calls[1]))
        self.assertNotIn("single fallback", calls[1])
        self.assertEqual(res.get("turn_mode"), "two-turn")
        self.assertEqual(res.get("turn1_exit"), 0)

    def test_missing_session_flags_send_the_single_fallback(self):
        log = Path(self.tmp.name) / "fallback.jsonl"
        instruction = (
            "turn one\n__OBENCH_USER_TURN__\nturn two\n"
            "__OBENCH_SINGLE_TURN__\nsingle fallback\n"
        )
        res = self._run(HELP_MODERN, {"FAKE_LOG": str(log)}, instruction=instruction)
        self.assertTrue(res["completed"], res.get("error"))
        calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(calls), 1)
        self.assertIn("single fallback", calls[0])
        self.assertNotIn("__OBENCH_USER_TURN__", " ".join(calls[0]))
        self.assertEqual(res.get("turn_mode"), "single")

    def test_turn1_failure_is_infra_and_skips_turn2(self):
        log = Path(self.tmp.name) / "failed-turn.jsonl"
        help_text = HELP_MODERN + "--session\n--continue\n"
        instruction = (
            "turn one\n__OBENCH_USER_TURN__\nturn two\n"
            "__OBENCH_SINGLE_TURN__\nsingle fallback\n"
        )
        res = self._run(help_text, {
            "FAKE_LOG": str(log),
            "FAKE_EXIT_CODE": "2",
            "FAKE_SESSION": "ses_from_first",
        }, instruction=instruction)
        self.assertFalse(res["completed"])
        self.assertEqual(res.get("failure_class"), "infra")
        self.assertEqual(res.get("turn_mode"), "turn-failure")
        self.assertEqual(res.get("turn1_exit"), 2)
        self.assertIn("turn 2 was not run", res.get("error") or "")
        calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(calls), 1)

    def test_old_layout_pyright_is_not_a_missing_worktree(self):
        root = Path(self.tmp.name) / "old-opencode"
        lsp = root / "packages" / "opencode" / "src" / "lsp"
        lsp.mkdir(parents=True)
        for name in ("client.ts", "index.ts", "language.ts", "server.ts"):
            (lsp / name).write_text("export const x = 1\n", encoding="utf-8")
        binary = root / "packages" / "opencode" / "dist" / "opencode"
        binary.parent.mkdir(parents=True)
        binary.write_text(FAKE, encoding="utf-8")
        binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
        bindir = Path(self.tmp.name) / "pyright-bin"
        bindir.mkdir()
        tool = bindir / "pyright-langserver"
        tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        tool.chmod(tool.stat().st_mode | stat.S_IEXEC)
        res = self._run(HELP_MODERN, {
            "OBENCH_OPENCODE_BIN": str(binary),
            "OBENCH_OPENCODE_LSP": "pyright",
            "PATH": os.pathsep.join([str(bindir), "/usr/bin", "/bin"]),
        })
        self.assertTrue(res["completed"], res.get("error"))
        self.assertNotIn("worktree", res.get("error") or "")
        dumped = self._dump()
        config = dumped.get("config") or ""
        self.assertNotIn('"lsp": true', config)
        self.assertNotIn('"lsp":true', config.replace(" ", ""))

    def test_missing_worktree_with_lsp_is_infra(self):
        bindir = Path(self.tmp.name) / "bin"
        bindir.mkdir()
        tool = bindir / "pyright-langserver"
        tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        tool.chmod(tool.stat().st_mode | stat.S_IEXEC)
        res = self._run(HELP_MODERN, {
            "OBENCH_OPENCODE_LSP": "pyright",
            "PATH": os.pathsep.join([str(bindir), "/usr/bin"]),
        })
        self.assertFalse(res["completed"])
        self.assertEqual(res.get("failure_class"), "infra")
        self.assertIn("worktree", res["error"])

    def test_missing_lsp_toolchain_fails_the_cell(self):
        res = self._run(HELP_MODERN, {
            "OBENCH_OPENCODE_LSP": "pyright",
            "OBENCH_OPENCODE_BUN": "/nonexistent/bun",
            "PATH": "/usr/bin",
        })
        self.assertFalse(res["completed"])
        self.assertIn("bun", res["error"])

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
        embedded = {"needs_sdk": False, "anthropic_sdk": "2.0.0"}
        self.assertEqual(
            opencode._provider_sdk_drift(env, proxy),
            "sdk drift: installed @ai-sdk/anthropic 4.0.72 != pin 2.0.0",
        )
        self.assertEqual(
            opencode._provider_sdk_drift(env, embedded),
            "sdk drift: installed @ai-sdk/anthropic 4.0.72 != pin 2.0.0",
        )
        module.write_text('{"version": "2.0.0"}', encoding="utf-8")
        self.assertEqual(opencode._provider_sdk_drift(env, proxy), "")
        self.assertEqual(opencode._provider_sdk_drift(env, embedded), "")

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
            (modern / "opencode-local.db").write_bytes(b"GLOBAL-RULE channel db")
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
            self.assertEqual(
                (modern_dest / "opencode-local.db").read_bytes(),
                b"GLOBAL-RULE channel db",
            )
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
