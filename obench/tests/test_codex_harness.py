"""Codex hard-suite comparison arm (obench/adapters/codex_harness.py).

No Codex binary and no network: the subprocess runner is a fake.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from obench import docker_exec
from obench.adapters import codex as codex_adapter
from obench.adapters import codex_harness as ch

ROOT = Path(__file__).resolve().parents[2]

TURN_JSONL = "\n".join(json.dumps(e) for e in [
    {"type": "thread.started", "thread_id": "t1"},
    {"type": "item.completed", "item": {"id": "i1", "type": "agent_message", "text": "Done."}},
    {"type": "turn.completed", "usage": {"input_tokens": 10700, "cached_input_tokens": 9000,
                                         "output_tokens": 340, "reasoning_output_tokens": 0}},
]) + "\n"

TOTALS = {
    "all": {"calls": 3, "input_uncached": 1200, "output": 340, "cache_read": 9000, "cache_write": 500},
    "main": {"calls": 3, "input_uncached": 1200, "output": 340, "cache_read": 9000, "cache_write": 500},
}


class FakeRunner:
    def __init__(self, version="codex-cli 0.144.5", returncode=0, stdout=TURN_JSONL, timeout=False):
        self.version = version
        self.returncode = returncode
        self.stdout = stdout
        self.timeout = timeout
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        if cmd[1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=self.version + "\n", stderr="")
        if self.timeout:
            raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"), output=b"partial", stderr=b"")
        return subprocess.CompletedProcess(cmd, self.returncode, stdout=self.stdout, stderr="")


class CellEnv(unittest.TestCase):
    def setUp(self):
        self.ledger = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ledger, True)
        self.workdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.workdir, True)
        env = {
            "OBENCH_VERTEX_PROXY_URL": "http://127.0.0.1:4567",
            "OBENCH_VERTEX_CELL_ID": "cellabc",
            "OBENCH_VERTEX_LEDGER_DIR": self.ledger,
            "OBENCH_CODEX_BIN": "/opt/codex/codex",
            "OPENAI_API_KEY": "sk-should-not-leak",
            "OPENAI_BASE_URL": "https://api.openai.com/v1",
        }
        patcher = patch.dict(os.environ, env, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("BENCH_IN_CONTAINER", "OBENCH_DOCKER_NETWORK", "OBENCH_CODEX_SETTINGS_PATH",
                     "OBENCH_CODEX_HARNESS"):
            os.environ.pop(name, None)

    def write_totals(self):
        Path(ch.totals_path(self.ledger, "cellabc")).write_text(json.dumps(TOTALS))


class CommandTests(unittest.TestCase):
    def cmd(self, **kw):
        return ch.build_command("/opt/codex/codex", "fix it", "claude-sonnet-5-5", "/work",
                                "http://127.0.0.1:4567/c/cellabc", in_container=kw.get("in_container", False))

    def test_provider_points_at_the_cell_proxy_responses_endpoint(self):
        cmd = self.cmd()
        joined = " ".join(cmd)
        self.assertIn('model_providers.obench_vertex.base_url="http://127.0.0.1:4567/c/cellabc/v1"', joined)
        self.assertIn('model_providers.obench_vertex.wire_api="responses"', joined)
        self.assertIn('model_providers.obench_vertex.env_key="OBENCH_CODEX_PROXY_KEY"', joined)
        self.assertIn('model_provider="obench_vertex"', joined)
        self.assertEqual(cmd[cmd.index("-m") + 1], "claude-sonnet-5-5")
        self.assertEqual(cmd[-1], "fix it")
        self.assertEqual(cmd[:3], ["/opt/codex/codex", "exec", "--json"])

    def test_ad1_context_window_and_reasoning(self):
        joined = " ".join(self.cmd())
        self.assertIn("model_context_window=200000", joined)
        self.assertIn('model_reasoning_effort="medium"', joined)
        self.assertEqual(ch.CONTEXT_WINDOW, 200_000)
        self.assertEqual(ch.ADAPTER_FIXES, ("AD1-codex-ctx",))
        self.assertNotIn("apply_patch", joined)  # AD1-codex-edit: nothing added

    def test_sandbox_and_features(self):
        self.assertIn("workspace-write", self.cmd())
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", self.cmd(in_container=True))
        cmd = self.cmd()
        for feature in ("apps", "plugins", "multi_agent"):
            self.assertIn(feature, cmd)
        self.assertIn("--skip-git-repo-check", cmd)

    def test_provider_base_url_and_cell_base(self):
        self.assertEqual(ch.cell_proxy_base("http://h:1/v1/", "c1"), "http://h:1/c/c1")
        self.assertEqual(ch.provider_base_url("http://h:1/c/c1/"), "http://h:1/c/c1/v1")


class PinTests(unittest.TestCase):
    def test_pin_is_exact(self):
        self.assertEqual(ch.PIN, "0.144.5")
        self.assertEqual(ch.require_pin("/x/codex", runner=FakeRunner()), "0.144.5")

    def test_wrong_or_missing_binary_fails_closed(self):
        with self.assertRaisesRegex(ch.PinError, "0.145.0"):
            ch.require_pin("/x/codex", runner=FakeRunner(version="codex-cli 0.145.0"))
        with self.assertRaisesRegex(ch.PinError, "OBENCH_CODEX_BIN"):
            ch.require_pin("", runner=FakeRunner())

        def broken(cmd, **kw):
            raise FileNotFoundError(cmd[0])
        with self.assertRaisesRegex(ch.PinError, "cannot run"):
            ch.require_pin("/missing/codex", runner=broken)

    def test_matches_the_harbor_profile_pin(self):
        from obench.harbor_profiles import _VERSIONS
        self.assertEqual(_VERSIONS["codex"], ch.PIN)

    def test_parse_version(self):
        self.assertEqual(ch.parse_version("codex-cli 0.144.5\n"), "0.144.5")
        self.assertIsNone(ch.parse_version("codex-cli"))


class RunTests(CellEnv):
    def test_run_meters_writes_settings_and_isolates_env(self):
        self.write_totals()
        runner = FakeRunner()
        row = ch.run("fix it", self.workdir, "claude-sonnet-5-5", 600, runner=runner)
        self.assertTrue(row["completed"], row)
        self.assertIsNone(row["error"])
        self.assertEqual(row["turns"], 1)
        self.assertEqual(row["model_context_window"], 200_000)
        self.assertEqual(row["adapter_fixes"], ["AD1-codex-ctx"])
        cmd, kwargs = runner.calls[-1]
        self.assertIn('model_providers.obench_vertex.base_url="http://127.0.0.1:4567/c/cellabc/v1"', " ".join(cmd))
        env = kwargs["env"]
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("OPENAI_BASE_URL", env)
        self.assertEqual(env["OBENCH_CODEX_PROXY_KEY"], ch.PROXY_KEY_VALUE)
        self.assertTrue(env["CODEX_HOME"].startswith(tempfile.gettempdir()) or "codex_harness_home_" in env["CODEX_HOME"])
        self.assertFalse(os.path.exists(env["CODEX_HOME"]))  # removed after the run
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
        settings = json.loads(Path(ch.settings_destination("cellabc", self.ledger)).read_text())
        self.assertEqual(settings["pin"], "0.144.5")
        self.assertEqual(settings["model_context_window"], 200_000)
        self.assertEqual(settings["auto_compact_at_tokens"], 180_000)
        self.assertEqual(settings["wire"]["path"], "/v1/responses")
        self.assertEqual(settings["proxy_totals"]["all"]["cache_read"], 9000)
        self.assertEqual(settings["side_calls"], 0)
        self.assertEqual(row["harness_settings"]["proxy_totals"], settings["proxy_totals"])

    def test_wrong_pin_fails_before_any_model_call(self):
        runner = FakeRunner(version="codex-cli 0.150.0")
        row = ch.run("fix it", self.workdir, "claude-sonnet-5-5", 600, runner=runner)
        self.assertFalse(row["completed"])
        self.assertIn("comparison pin is 0.144.5", row["error"])
        self.assertEqual(len(runner.calls), 1)  # only --version

    def test_setup_errors_fail_closed(self):
        self.assertIn("does not run model",
                      ch.run("x", self.workdir, "gpt-5.5-medium", 60, runner=FakeRunner())["error"])
        with patch.dict(os.environ, {"OBENCH_VERTEX_CELL_ID": "bad id!"}):
            self.assertIn("OBENCH_VERTEX_CELL_ID",
                          ch.run("x", self.workdir, "claude-sonnet-5-5", 60, runner=FakeRunner())["error"])
        os.environ.pop("OBENCH_CODEX_BIN")
        self.assertIn("OBENCH_CODEX_BIN",
                      ch.run("x", self.workdir, "claude-sonnet-5-5", 60, runner=FakeRunner())["error"])

    def test_missing_totals_and_failures_are_reported(self):
        row = ch.run("x", self.workdir, "claude-sonnet-5-5", 60, runner=FakeRunner(returncode=3))
        self.assertFalse(row["completed"])
        self.assertEqual(row["error"], "exit 3")
        self.assertIn("proxy totals missing", row["harness_settings"]["proxy_totals_error"])
        row = ch.run("x", self.workdir, "claude-sonnet-5-5", 60, runner=FakeRunner(timeout=True))
        self.assertEqual(row["failure_class"], "timeout")
        self.assertIn("timeout after 60s", row["error"])

    def test_docker_network_rewrites_the_loopback_proxy(self):
        with patch.dict(os.environ, {"OBENCH_DOCKER_NETWORK": "bridge", "BENCH_IN_CONTAINER": "1"}):
            runner = FakeRunner()
            ch.run("x", self.workdir, "claude-sonnet-5-5", 60, runner=runner)
        joined = " ".join(runner.calls[-1][0])
        self.assertNotIn("127.0.0.1", joined)
        self.assertIn("/c/cellabc/v1", joined)
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", joined)


class DispatchTests(CellEnv):
    def test_codex_run_dispatches_comparison_models(self):
        with patch.object(ch, "run", return_value={"completed": True, "via": "harness"}) as run:
            row = codex_adapter.run("fix", self.workdir, "claude-sonnet-5-5", 60)
        self.assertEqual(row["via"], "harness")
        run.assert_called_once_with("fix", self.workdir, "claude-sonnet-5-5", 60)

    def test_subscription_models_keep_the_stock_path(self):
        with patch.object(ch, "run") as run, \
                patch.object(codex_adapter.subprocess, "run",
                             return_value=subprocess.CompletedProcess([], 0, stdout=TURN_JSONL, stderr="")):
            codex_adapter.run("fix", self.workdir, "gpt-5.5-medium", 60)
        run.assert_not_called()

    def test_a_url_set_routes_through_the_proxy_to_the_cell_base(self):
        """Rule: a Claude-model Codex cell reaches the Vertex proxy when the URL is set.
        No other flag is needed to route."""
        for flag in (None, "0", "1"):
            with patch.dict(os.environ, {} if flag is None else {"OBENCH_CODEX_HARNESS": flag}):
                with patch.object(ch, "run", return_value={"completed": True, "via": "harness"}) as harness_run:
                    row = codex_adapter.run("fix", self.workdir, "claude-sonnet-5-5", 60)
                self.assertEqual(row["via"], "harness", flag)
                harness_run.assert_called_once_with("fix", self.workdir, "claude-sonnet-5-5", 60)
                runner = FakeRunner()
                routed = ch.run("fix", self.workdir, "claude-opus-5-5", 60, runner=runner)
                self.assertTrue(routed["completed"], flag)
                cmd = runner.calls[-1][0]
                self.assertIn('model_providers.obench_vertex.base_url="http://127.0.0.1:4567/c/cellabc/v1"',
                              " ".join(cmd))
                self.assertIn('model_provider="obench_vertex"', cmd)

    def _assert_fails_closed(self, extra_env):
        """No codex process, no socket, no HTTP request: the cell fails before any of them."""
        env = {"OBENCH_VERTEX_PROXY_URL": ""}
        env.update(extra_env)
        with patch.dict(os.environ, env), \
                patch.object(subprocess, "Popen", side_effect=AssertionError("codex invoked")) as popen, \
                patch("urllib.request.urlopen", side_effect=AssertionError("network call")) as urlopen, \
                patch("socket.create_connection", side_effect=AssertionError("network call")) as connect:
            for model in ("claude-sonnet-5-5", "claude-opus-5-5"):
                row = codex_adapter.run("fix", self.workdir, model, 60)
                self.assertFalse(row["completed"])
                self.assertEqual(row["error"], f"Codex harness cell for {model} needs OBENCH_VERTEX_PROXY_URL "
                                               "(the Vertex proxy address); refusing to run without the proxy")
                self.assertIsNone(row["cmd"])
                self.assertIsNone(row["tokens"])
            runner = FakeRunner()
            direct = ch.run("fix", self.workdir, "claude-sonnet-5-5", 60, runner=runner)
            self.assertFalse(direct["completed"])
            self.assertEqual(runner.calls, [])  # not even `codex --version`
        popen.assert_not_called()
        urlopen.assert_not_called()
        connect.assert_not_called()

    def test_b_url_unset_fails_closed_without_running_codex(self):
        self._assert_fails_closed({})

    def test_c_url_unset_with_harness_flag_still_fails_closed(self):
        self._assert_fails_closed({"OBENCH_CODEX_HARNESS": "1"})

    def test_claude_model_never_takes_the_stock_codex_path(self):
        """Even if the harness module returned control, the stock argv is never built."""
        for url in ("", "http://127.0.0.1:4567"):
            with patch.dict(os.environ, {"OBENCH_VERTEX_PROXY_URL": url}), \
                    patch.object(codex_adapter.subprocess, "run") as stock_run, \
                    patch.object(ch, "run", wraps=ch.run) as harness_run:
                codex_adapter.run("fix", self.workdir, "claude-sonnet-5-5", 60)
            harness_run.assert_called_once()
            stock_run.assert_not_called()


class DockerArgsTests(CellEnv):
    def test_claude_model_codex_cells_get_env_mount_and_sinkholes(self):
        with patch("thesis.ab.proxy_bridge.shared_proxy_port", return_value=4567):
            args = docker_exec._proxy_bridge_docker_args("codex", [], "claude-sonnet-5-5")
        self.assertIn("OBENCH_VERTEX_PROXY_URL", args)
        self.assertIn("OBENCH_VERTEX_CELL_ID", args)
        self.assertNotIn("OBENCH_CODEX_HARNESS", args)
        self.assertIn("/opt/codex:/opt/openbench-codex:ro", args)
        self.assertIn("OBENCH_CODEX_BIN=/opt/openbench-codex/codex", args)
        self.assertIn("--add-host=api.openai.com:0.0.0.0", args)
        self.assertIn("--add-host=chatgpt.com:0.0.0.0", args)
        self.assertIn("--add-host=api.anthropic.com:0.0.0.0", args)
        self.assertNotIn("OPENAI_API_KEY", args)

    def test_stock_gpt_codex_cells_are_unchanged(self):
        """A Pi run's exported proxy URL does not touch a stock GPT-model Codex cell."""
        for model in ("gpt-5.5-medium", "gpt-5.6-sol", None):
            self.assertEqual(docker_exec._proxy_bridge_docker_args("codex", [], model), [], model)
        with patch.dict(os.environ, {"OBENCH_VERTEX_PROXY_URL": ""}):
            self.assertEqual(docker_exec._proxy_bridge_docker_args("codex", [], "gpt-5.5-medium"), [])

    def test_build_docker_cmd_passes_the_model(self):
        cmd = docker_exec.build_docker_cmd(
            harness="codex", workdir="/tmp/wd", model="claude-sonnet-5-5", timeout_s=60,
            adapters_dir="/repo/obench/adapters", image="img:1", instruction_path="/tmp/instr")
        self.assertIn("OBENCH_CODEX_BIN=/opt/openbench-codex/codex", cmd)
        stock = docker_exec.build_docker_cmd(
            harness="codex", workdir="/tmp/wd", model="gpt-5.5-medium", timeout_s=60,
            adapters_dir="/repo/obench/adapters", image="img:1", instruction_path="/tmp/instr")
        self.assertNotIn("OBENCH_VERTEX_PROXY_URL", stock)


class LauncherTests(unittest.TestCase):
    def load(self):
        import importlib.util
        path = ROOT / "data" / "codex-harness-smoke" / "cell.py"
        spec = importlib.util.spec_from_file_location("codex_harness_smoke_cell", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_out_dir_refuses_results_and_data(self):
        cell = self.load()
        for bad in ("/tmp/x/results/smoke", "/home/box/openbench/data/codex", "results"):
            with self.assertRaises(SystemExit):
                cell.check_out_dir(Path(bad))
        ok = cell.check_out_dir(Path(tempfile.gettempdir()) / "codex-harness-smoke")
        self.assertTrue(ok.is_absolute())

    def test_launcher_defaults_match_the_other_arms(self):
        cell = self.load()
        self.assertEqual(cell.MODEL_ID, "claude-sonnet-5-5")
        self.assertEqual(cell.TIMEOUT_S, 2400)
        self.assertEqual(cell.TASK, "polyglot-rust-c")
        args = cell.argument_parser().parse_args(["--out", "/tmp/o"])
        self.assertTrue(args.require_model_match)


if __name__ == "__main__":
    unittest.main()
