"""Hermes hard-suite comparison arm (obench/adapters/hermes_harness.py).

No Hermes install and no network: the subprocess runner and the gateway
stopper are fakes.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from obench import docker_exec
from obench.adapters import hermes as hermes_adapter
from obench.adapters import hermes_harness as hh

ROOT = Path(__file__).resolve().parents[2]
USAGE = {"api_calls": 3, "input_tokens": 120000, "output_tokens": 4000,
         "auxiliary": {"by_task": {"title_generation": {"api_calls": 1, "input_tokens": 900}}},
         "total_including_auxiliary": {"api_calls": 4}}


class FakeRunner:
    """Plays `hermes -z ... --usage-file F`: records the call and the config it saw."""

    def __init__(self, returncode=0, usage=USAGE, timeout=False):
        self.returncode, self.usage, self.timeout = returncode, usage, timeout
        self.calls = []
        self.config = None

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        home = kwargs["env"]["HERMES_HOME"]
        self.config = json.loads(Path(home, "config.yaml").read_text())
        if self.usage is not None:
            Path(cmd[cmd.index("--usage-file") + 1]).write_text(json.dumps(self.usage))
        if self.timeout:
            raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"), output=b"partial", stderr=b"")
        return subprocess.CompletedProcess(cmd, self.returncode, stdout="done\n", stderr="")


class GatewaySpy:
    def __init__(self):
        self.calls = []

    def __call__(self, binary, home):
        self.calls.append((binary, home, os.path.isdir(home)))
        return {"stop_command": 0, "signalled": [], "survivors": []}


class CellEnv(unittest.TestCase):
    def setUp(self):
        self.ledger = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ledger, True)
        self.workdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.workdir, True)
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        Path(self.root, "PIN").write_text(hh.PIN + "\n")
        env = {
            "OBENCH_HERMES_HARNESS": "1",
            "OBENCH_VERTEX_PROXY_URL": "http://127.0.0.1:4567",
            "OBENCH_VERTEX_CELL_ID": "cellh",
            "OBENCH_VERTEX_LEDGER_DIR": self.ledger,
            "OBENCH_HERMES_BIN": os.path.join(self.root, "bin", "hermes"),
            "OBENCH_HERMES_ROOT": self.root,
            "ANTHROPIC_API_KEY": "sk-ant-should-not-leak",
            "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
        }
        patcher = patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("OBENCH_DOCKER_NETWORK", "OBENCH_HERMES_PIN_FILE", "OBENCH_HERMES_SETTINGS_PATH"):
            os.environ.pop(name, None)

    def run_cell(self, runner=None, gateway=None):
        runner = runner or FakeRunner()
        gateway = gateway or GatewaySpy()
        row = hh.run("fix it", self.workdir, "claude-sonnet-5-5", 600, runner=runner, gateway_stopper=gateway)
        return row, runner, gateway


class Gating(CellEnv):
    def test_flag_and_url_route_to_the_harness(self):
        with patch.object(hh, "run", return_value={"completed": True, "via": "harness"}) as harness_run:
            row = hermes_adapter.run("fix", self.workdir, "claude-sonnet-5-5", 60)
        self.assertEqual(row["via"], "harness")
        harness_run.assert_called_once_with("fix", self.workdir, "claude-sonnet-5-5", 60)
        row, runner, _ = self.run_cell()
        self.assertTrue(row["completed"], row)
        self.assertEqual(runner.config["providers"]["proxy"]["api"], "http://127.0.0.1:4567/c/cellh")

    def test_flag_off_is_stock_hermes_even_with_a_proxy_url(self):
        with patch.dict(os.environ, {"OBENCH_HERMES_HARNESS": ""}), \
                patch.object(hh, "run") as harness_run, \
                patch.object(hermes_adapter.shutil, "which", return_value=None):
            row = hermes_adapter.run("fix", self.workdir, "claude-sonnet-5-5", 60)
        harness_run.assert_not_called()
        self.assertIn("hermes is not on PATH", row["error"])  # stock path, no proxy config

    def test_flag_on_without_url_fails_closed_before_any_process(self):
        with patch.dict(os.environ, {"OBENCH_VERTEX_PROXY_URL": ""}), \
                patch.object(subprocess, "Popen", side_effect=AssertionError("hermes started")) as popen:
            runner, gateway = FakeRunner(), GatewaySpy()
            row = hh.run("fix", self.workdir, "claude-sonnet-5-5", 60, runner=runner, gateway_stopper=gateway)
            stock = hermes_adapter.run("fix", self.workdir, "claude-sonnet-5-5", 60)
        self.assertFalse(row["completed"])
        self.assertEqual(row["error"], "Hermes harness comparison: OBENCH_HERMES_HARNESS=1 is set but "
                                       "OBENCH_VERTEX_PROXY_URL (the proxy address) is missing")
        self.assertEqual(stock["error"], row["error"])
        self.assertEqual(runner.calls, [])
        self.assertEqual(gateway.calls, [])
        popen.assert_not_called()

    def test_flag_values_and_models(self):
        for value in ("1", "true", "YES", "on"):
            with patch.dict(os.environ, {"OBENCH_HERMES_HARNESS": value}):
                self.assertTrue(hh.comparison_requested())
        for value in ("", "0", "off"):
            with patch.dict(os.environ, {"OBENCH_HERMES_HARNESS": value}):
                self.assertFalse(hh.comparison_requested())
        self.assertIn("does not run model", hh.run("x", self.workdir, "gpt-5.5-medium", 60)["error"])


class Config(unittest.TestCase):
    def setUp(self):
        self.cfg = hh.benchmark_config("http://127.0.0.1:4567/c/cellh", "claude-sonnet-5-5")

    def test_proxy_provider_on_the_anthropic_messages_wire(self):
        self.assertEqual(self.cfg["model"], {"provider": "custom:proxy", "default": "claude-sonnet-5-5"})
        provider = self.cfg["providers"]["proxy"]
        self.assertEqual(provider["api"], "http://127.0.0.1:4567/c/cellh")
        self.assertEqual(provider["transport"], "anthropic_messages")
        self.assertFalse(provider["discover_models"])

    def test_context_length_is_the_named_constant(self):
        self.assertEqual(hh.CONTEXT_LENGTH, 1_000_000)
        self.assertEqual(self.cfg["providers"]["proxy"]["models"]["claude-sonnet-5-5"]["context_length"],
                         hh.CONTEXT_LENGTH)

    def test_thinking_is_left_unset(self):
        """No agent.reasoning_effort: Hermes sends no `thinking` (matching OpenCode).
        Hermes's own "none" would send thinking: between_tools."""
        self.assertNotIn("agent", self.cfg)
        self.assertNotIn("reasoning_effort", json.dumps(self.cfg))

    def test_overrides_and_stock_defaults(self):
        self.assertEqual(self.cfg["memory"], {"memory_enabled": False, "user_profile_enabled": False,
                                              "nudge_interval": 0})
        self.assertEqual(self.cfg["approvals"], {"mode": "off"})
        self.assertFalse(self.cfg["lsp"]["enabled"])
        self.assertFalse(self.cfg["model_catalog"]["enabled"])
        self.assertFalse(self.cfg["updates"]["check"])
        self.assertFalse(self.cfg["security"]["allow_lazy_installs"])
        self.assertFalse(self.cfg["curator"]["enabled"])
        self.assertEqual(self.cfg["gateway"]["unmanaged_idle_exit_seconds"], hh.GATEWAY_IDLE_EXIT_S)
        # Stock: title generation on, toolset and rules untouched.
        self.assertNotIn("title_generation", self.cfg["auxiliary"])
        self.assertNotIn("disabled_toolsets", json.dumps(self.cfg))
        for _setting, row, why in hh.BENCHMARK_OVERRIDES:
            self.assertIsInstance(row, int)
            self.assertTrue(why)

    def test_command_is_one_shot_with_usage_file_and_no_model_flags(self):
        cmd = hh.build_command("/r/bin/hermes", "do it", "/h/usage.json")
        self.assertEqual(cmd, ["/r/bin/hermes", "-z", "do it", "--usage-file", "/h/usage.json"])
        self.assertNotIn("--ignore-rules", cmd)
        self.assertNotIn("-m", cmd)


class Pin(CellEnv):
    def test_pin_stamp_must_match(self):
        self.assertEqual(hh.require_pin(os.environ["OBENCH_HERMES_BIN"]), hh.PIN)
        Path(self.root, "PIN").write_text("deadbeef\n")
        with self.assertRaisesRegex(hh.PinError, "comparison pin"):
            hh.require_pin(os.environ["OBENCH_HERMES_BIN"])
        os.remove(Path(self.root, "PIN"))
        with self.assertRaisesRegex(hh.PinError, "missing"):
            hh.require_pin(os.environ["OBENCH_HERMES_BIN"])
        with self.assertRaisesRegex(hh.PinError, "OBENCH_HERMES_BIN"):
            hh.require_pin("")
        self.assertEqual((hh.PIN[:8], hh.LICENSE), ("4dcef215", "MIT"))

    def test_wrong_pin_fails_before_hermes_runs(self):
        Path(self.root, "PIN").write_text("v0.22.6\n")
        row, runner, gateway = self.run_cell()
        self.assertIn("comparison pin", row["error"])
        self.assertEqual(runner.calls, [])
        self.assertEqual(gateway.calls, [])


class Run(CellEnv):
    def test_run_isolates_home_counts_every_call_and_records_settings(self):
        row, runner, gateway = self.run_cell()
        cmd, kwargs = runner.calls[-1]
        env = kwargs["env"]
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("ANTHROPIC_BASE_URL", env)
        self.assertTrue(env["HERMES_HOME"].startswith(tempfile.gettempdir()) or "hermes_harness_home_" in env["HERMES_HOME"])
        self.assertEqual(kwargs["cwd"], self.workdir)
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
        # Every call traced: 3 main + 1 title side call.
        self.assertEqual(row["turns"], 4)
        self.assertEqual(row["main_calls"], 3)
        self.assertEqual(row["aux_calls"], {"title_generation": 1})
        self.assertEqual(row["usage_raw"], USAGE)
        # Gateway stopped while the home still existed, then the home removed.
        self.assertEqual(len(gateway.calls), 1)
        binary, home, existed = gateway.calls[0]
        self.assertEqual(home, env["HERMES_HOME"])
        self.assertTrue(existed)
        self.assertFalse(os.path.exists(home))
        settings = json.loads(Path(hh.settings_destination("cellh", self.ledger)).read_text())
        self.assertEqual(settings["pin"], hh.PIN)
        self.assertEqual(settings["license"], "MIT")
        self.assertEqual(settings["context_length"], 1_000_000)
        self.assertIn("pending Researcher", settings["context_length_status"])
        self.assertEqual(settings["turns"], 4)
        self.assertEqual({o["sheet_row"] for o in settings["benchmark_overrides"]}, {6, 11, 13, 14, 26, 32})
        self.assertEqual(row["harness_pin"], hh.PIN)
        self.assertEqual(row["context_length"], hh.CONTEXT_LENGTH)

    def test_timeout_still_stops_the_gateway(self):
        row, _, gateway = self.run_cell(runner=FakeRunner(timeout=True))
        self.assertEqual(row["failure_class"], "timeout")
        self.assertEqual(row["turns"], 4)
        self.assertEqual(len(gateway.calls), 1)

    def test_missing_usage_file_and_nonzero_exit(self):
        row, _, gateway = self.run_cell(runner=FakeRunner(returncode=2, usage=None))
        self.assertEqual(row["error"], "exit 2")
        self.assertIsNone(row["turns"])
        self.assertEqual(len(gateway.calls), 1)

    def test_trace_matches_a_four_request_ledger(self):
        from thesis.ab.run_ab import attach_proxy_trace
        row, _, _ = self.run_cell()
        ledger = [{"usage": {"input_tokens": 1}, "upstream_model": "claude-sonnet-5-5",
                   "requested_model": "claude-sonnet-5-5", "endpoint_location": "global"} for _ in range(4)]
        attach_proxy_trace(row, ledger, "claude-sonnet-5-5", ledger_present=True)
        self.assertEqual((row["trace_requests"], row["untraced_requests"]), (4, 0))

    def test_docker_network_rewrites_the_loopback_proxy(self):
        with patch.dict(os.environ, {"OBENCH_DOCKER_NETWORK": "bridge"}):
            _, runner, _ = self.run_cell()
        self.assertNotIn("127.0.0.1", runner.config["providers"]["proxy"]["api"])
        self.assertTrue(runner.config["providers"]["proxy"]["api"].endswith("/c/cellh"))


class Usage(unittest.TestCase):
    def test_parse_usage_variants(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, "u.json")
            path.write_text(json.dumps({"calls": 2, "auxiliary": {"by_task": {
                "title_generation": {"api_call_count": 1}, "compression": {"calls": 0}}}}))
            parsed = hh.parse_usage(str(path))
            self.assertEqual((parsed["main_calls"], parsed["aux_calls"], parsed["total_calls"]),
                             (2, {"title_generation": 1}, 3))
            path.write_text("not json")
            self.assertFalse(hh.parse_usage(str(path))["present"])
        self.assertIsNone(hh.parse_usage("/nonexistent/usage.json")["total_calls"])


class Gateway(unittest.TestCase):
    def test_stop_command_then_signals_survivors(self):
        calls, kills = [], []
        rounds = [[101, 102], [102]]

        def runner(cmd, **kw):
            calls.append((cmd, kw["env"]["HERMES_HOME"]))
            return subprocess.CompletedProcess(cmd, 0, "", "")

        result = hh.stop_gateway("/r/bin/hermes", "/tmp/h1", runner=runner,
                                 find_pids=lambda home: rounds.pop(0) if rounds else [],
                                 kill=lambda pid, sig: kills.append((pid, sig)), sleep=lambda s: None)
        self.assertEqual(calls, [(["/r/bin/hermes", "gateway", "stop"], "/tmp/h1")])
        self.assertEqual(kills, [(101, signal.SIGTERM), (102, signal.SIGTERM), (102, signal.SIGKILL)])
        self.assertEqual(result["signalled"], [101, 102])
        self.assertEqual(result["survivors"], [102])

    def test_proc_scan_matches_only_this_home(self):
        with tempfile.TemporaryDirectory() as proc:
            for pid, environ in (("11", b"PATH=/bin\0HERMES_HOME=/tmp/h1\0"), ("12", b"HERMES_HOME=/tmp/h2\0"),
                                 ("self", b"HERMES_HOME=/tmp/h1\0")):
                os.makedirs(os.path.join(proc, pid))
                Path(proc, pid, "environ").write_bytes(environ)
            self.assertEqual(hh._proc_pids_with_home("/tmp/h1", proc_root=proc), [11])

    def test_stop_survives_a_missing_binary(self):
        def broken(cmd, **kw):
            raise FileNotFoundError(cmd[0])
        result = hh.stop_gateway("/missing/hermes", "/tmp/h1", runner=broken, find_pids=lambda h: [])
        self.assertTrue(str(result["stop_command"]).startswith("error"))


class DockerArgs(CellEnv):
    def test_flagged_cells_get_env_root_mount_and_sinkholes(self):
        with patch("thesis.ab.proxy_bridge.shared_proxy_port", return_value=4567):
            args = docker_exec._proxy_bridge_docker_args("hermes", [])
        for name in ("OBENCH_HERMES_HARNESS", "OBENCH_VERTEX_PROXY_URL", "OBENCH_HERMES_BIN", "OBENCH_HERMES_ROOT"):
            self.assertIn(name, args)
        root = os.path.abspath(self.root)
        self.assertIn(f"{root}:{root}:ro", args)
        self.assertIn("--add-host=api.anthropic.com:0.0.0.0", args)
        self.assertIn("--add-host=inference-api.nousresearch.com:0.0.0.0", args)
        self.assertNotIn("ANTHROPIC_API_KEY", args)

    def test_stock_cells_are_untouched(self):
        with patch.dict(os.environ, {"OBENCH_HERMES_HARNESS": ""}):
            self.assertEqual(docker_exec._proxy_bridge_docker_args("hermes", []), [])


class Launcher(unittest.TestCase):
    def load(self):
        import importlib.util
        path = ROOT / "data" / "hermes-harness-smoke" / "cell.py"
        spec = importlib.util.spec_from_file_location("hermes_harness_smoke_cell", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_out_dir_refuses_results_and_data(self):
        cell = self.load()
        for bad in ("/tmp/x/results/smoke", "/home/box/openbench/data/hermes"):
            with self.assertRaises(SystemExit):
                cell.check_out_dir(Path(bad))
        self.assertTrue(cell.check_out_dir(Path(tempfile.gettempdir()) / "hermes-harness-smoke").is_absolute())

    def test_defaults_match_the_other_arms(self):
        cell = self.load()
        self.assertEqual((cell.MODEL_ID, cell.TIMEOUT_S, cell.TASK), ("claude-sonnet-5-5", 2400, "polyglot-rust-c"))
        self.assertTrue(cell.argument_parser().parse_args(["--out", "/tmp/o"]).require_model_match)

    def test_prep_script_pins_the_commit(self):
        text = (ROOT / "data" / "hermes-harness-smoke" / "prep.sh").read_text()
        self.assertIn(f"PIN={hh.PIN}", text)
        self.assertIn("--commit \"$PIN\"", text)
        self.assertIn("pm install --extra anthropic", text)
        self.assertIn("refusing to install under results/ or data/", text)


if __name__ == "__main__":
    unittest.main()
