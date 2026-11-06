"""Hermes hard-suite comparison arm (obench/adapters/hermes_harness.py).

No Hermes install and no network: the subprocess runner and the gateway
stopper are fakes.
"""

from __future__ import annotations

import contextlib
import io
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

    def __call__(self, entry, home):
        self.calls.append((entry, home, os.path.isdir(home)))
        return {"stop_command": 0, "signalled": [], "survivors": []}


def fake_install(root):
    """The layout install.sh + `hermes pm install` leave under the root."""
    src = Path(root, "src")
    launcher = src / ".hermes" / "bin" / "hermes"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\nexec store-python -I -c bootstrap \"$@\"\n")
    (src / "hermes").write_text("from hermes_cli.main import main\n")
    state = Path(root, "home", "installs", hh.install_key(str(src)))
    generation = state / "environments" / "728a8e5eb0f7423c837b5c99dddcb14d"
    venv = generation / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").write_text("")
    (venv / "pyvenv.cfg").write_text("home = /x\n")
    (generation / "workspace").mkdir()
    for name in ("inputs", "pm-runtime"):
        (state / name).mkdir()
    (state / "declined-packages.json").write_text("{}")
    (state / "facts.json").write_text(json.dumps(vm_facts(state, venv), indent=2))
    return str(launcher), str(venv / "bin" / "python"), str(src / "hermes"), state


def vm_facts(state, venv):
    """facts.json exactly as `hermes pm install --extra anthropic` wrote it on the VM."""
    return {
        "packages": {
            "venv": {
                "environment": str(venv),
                "extras": ["all", "anthropic"],
                "resolved_lock": str(venv.parent / "workspace" / "uv.lock"),
                "stamp": "198320d6",
            }
        },
        "schema": 1,
    }


class CellEnv(unittest.TestCase):
    def setUp(self):
        self.ledger = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ledger, True)
        self.workdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.workdir, True)
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        Path(self.root, "PIN").write_text(hh.PIN + "\n")
        self.launcher, self.python, self.entry, self.state = fake_install(self.root)
        env = {
            "OBENCH_HERMES_HARNESS": "1",
            "OBENCH_VERTEX_PROXY_URL": "http://127.0.0.1:4567",
            "OBENCH_VERTEX_CELL_ID": "cellh",
            "OBENCH_VERTEX_LEDGER_DIR": self.ledger,
            "OBENCH_HERMES_BIN": self.launcher,
            "OBENCH_HERMES_ROOT": self.root,
            "ANTHROPIC_API_KEY": "sk-ant-should-not-leak",
            "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
            "PYTHONPATH": "/somewhere/else",
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
        self.assertEqual(runner.config["providers"]["proxy"]["api"],
                         "http://127.0.0.1:4567/c/cellh/strip-beta/interleaved-thinking-2025-05-14")

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
        self.assertEqual(hh.CONTEXT_LENGTH, 200_000)
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
        cmd = hh.build_command(["/r/venv/bin/python", "/r/src/hermes"], "do it", "/h/usage.json")
        self.assertEqual(cmd, ["/r/venv/bin/python", "/r/src/hermes", "-z", "do it", "--usage-file", "/h/usage.json"])
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
        self.assertEqual(settings["context_length"], 200_000)
        self.assertTrue(settings["context_length_status"].startswith("decided: 200K"))
        self.assertNotIn("pending", json.dumps(settings))
        self.assertEqual(settings["adapter_fixes"], ["AD1-hermes-ctx", "AD1-hermes-beta"])
        self.assertEqual(settings["stripped_betas"], ["interleaved-thinking-2025-05-14"])
        self.assertEqual(row["adapter_fixes"], ["AD1-hermes-ctx", "AD1-hermes-beta"])
        self.assertEqual(settings["turns"], 4)
        self.assertEqual({o["sheet_row"] for o in settings["benchmark_overrides"]}, {6, 9, 11, 13, 14, 26, 32})
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
        self.assertTrue(runner.config["providers"]["proxy"]["api"].endswith(
            "/c/cellh/strip-beta/interleaved-thinking-2025-05-14"))


class Launch(CellEnv):
    def test_cell_runs_the_committed_environment_on_the_entry_script(self):
        row, runner, gateway = self.run_cell()
        cmd, kwargs = runner.calls[-1]
        self.assertEqual(cmd[:2], [self.python, self.entry])
        self.assertNotIn(self.launcher, cmd)
        env = kwargs["env"]
        self.assertEqual(env["HERMES_DISABLE_LAZY_INSTALLS"], "1")
        self.assertEqual(env["PYTHONNOUSERSITE"], "1")
        self.assertNotIn("PYTHONPATH", env)
        self.assertEqual(gateway.calls[0][0], [self.python, self.entry])
        launch = row["harness_settings"]["launch"]
        self.assertEqual((launch["python"], launch["entry"]), (self.python, self.entry))
        self.assertEqual(launch["env"]["HERMES_DISABLE_LAZY_INSTALLS"], "1")

    def assert_fails_closed(self, pattern):
        row, runner, gateway = self.run_cell()
        self.assertFalse(row["completed"])
        self.assertRegex(row["error"], pattern)
        self.assertEqual(runner.calls, [])
        self.assertEqual(gateway.calls, [])

    def test_binary_outside_the_root_fails_closed(self):
        outside = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, outside, True)
        shim = Path(outside, "hermes")
        shim.write_text("")
        with patch.dict(os.environ, {"OBENCH_HERMES_BIN": str(shim)}):
            self.assert_fails_closed(r"OBENCH_HERMES_BIN .* is not under OBENCH_HERMES_ROOT .*src/\.hermes/bin/hermes")
        # A symlink inside the root that points outside it is outside too.
        link = Path(self.root, "src", ".hermes", "bin", "hermes-link")
        link.symlink_to(shim)
        with patch.dict(os.environ, {"OBENCH_HERMES_BIN": str(link)}):
            self.assert_fails_closed("is not under OBENCH_HERMES_ROOT")

    def test_missing_root_or_dependency_record_fails_closed(self):
        with patch.dict(os.environ, {"OBENCH_HERMES_ROOT": ""}):
            with self.assertRaisesRegex(hh.LaunchError, "needs OBENCH_HERMES_ROOT"):
                hh.resolve_launch("", self.launcher)
        os.remove(self.state / "facts.json")
        self.assert_fails_closed(r"dependency record is unreadable: .*facts\.json")

    def write_facts(self, mutate):
        facts = json.loads((self.state / "facts.json").read_text())
        mutate(facts)
        (self.state / "facts.json").write_text(json.dumps(facts))

    def test_vm_facts_shape_resolves_the_venv_and_records_extras(self):
        launch = hh.resolve_launch(self.root, self.launcher)
        self.assertEqual(launch["python"], self.python)
        self.assertTrue(launch["environment"].endswith("/environments/728a8e5eb0f7423c837b5c99dddcb14d/venv"))
        self.assertEqual(launch["extras"], ["all", "anthropic"])
        row, _, _ = self.run_cell()
        self.assertEqual(row["harness_settings"]["launch"]["extras"], ["all", "anthropic"])
        settings = json.loads(Path(hh.settings_destination("cellh", self.ledger)).read_text())
        self.assertEqual(settings["launch"]["extras"], ["all", "anthropic"])

    def test_environment_outside_the_install_fails_closed(self):
        outside = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, outside, True)
        self.write_facts(lambda f: f["packages"]["venv"].update(environment=outside))
        self.assert_fails_closed("outside the install root")

    def test_other_facts_shapes_fail_closed(self):
        cases = [
            (lambda f: f.update(schema=2), "schema 2, expected 1"),
            (lambda f: f.pop("schema"), "schema None, expected 1"),
            (lambda f: f["packages"].pop("venv"), r"names no environment \(packages\.venv\.environment\)"),
            (lambda f: f["packages"]["venv"].pop("environment"), "names no environment"),
            (lambda f: f.update(packages=[]), "names no environment"),
            (lambda f: f["packages"]["venv"].update(extras="all"), "malformed packages.venv.extras"),
        ]
        original = (self.state / "facts.json").read_text()
        for mutate, pattern in cases:
            with self.subTest(pattern=pattern):
                (self.state / "facts.json").write_text(original)
                self.write_facts(mutate)
                self.assert_fails_closed(pattern)
        # The pre-schema flat shape (the old fixture) is rejected too.
        (self.state / "facts.json").write_text(json.dumps({"environment": str(Path(self.python).parents[1])}))
        self.assert_fails_closed("schema None")

    def test_absent_extras_are_recorded_as_none(self):
        self.write_facts(lambda f: f["packages"]["venv"].pop("extras"))
        self.assertIsNone(hh.resolve_launch(self.root, self.launcher)["extras"])

    def test_environment_without_pyvenv_cfg_fails_closed(self):
        os.remove(Path(self.python).parents[1] / "pyvenv.cfg")
        self.assert_fails_closed("no pyvenv.cfg")

    def test_missing_interpreter_fails_closed(self):
        os.remove(self.python)
        self.assert_fails_closed("interpreter is missing")

    def test_unstartable_interpreter_is_a_clean_error_not_a_traceback(self):
        def broken(cmd, **kw):
            raise FileNotFoundError(2, "No such file or directory", cmd[0])
        gateway = GatewaySpy()
        row = hh.run("fix", self.workdir, "claude-sonnet-5-5", 60, runner=broken, gateway_stopper=gateway)
        self.assertFalse(row["completed"])
        self.assertIn(f"could not start {self.python}", row["error"])
        self.assertEqual(len(gateway.calls), 1)

    def test_docker_smoke_mirrors_the_cell(self):
        launch = hh.resolve_launch(self.root, self.launcher)
        commands = dict(hh.smoke_commands(launch))
        self.assertEqual(commands["version"], [self.python, self.entry, "--version"])
        self.assertEqual(commands["imports"][:2], [self.python, "-c"])
        for module in ("hermes_bootstrap", "hermes_yaml", "ruamel.yaml", "anthropic"):
            self.assertIn(module, commands["imports"][2])
        argv = hh.docker_smoke_argv("h1-env:1027-strace", self.root, commands["version"])
        root = os.path.abspath(self.root)
        self.assertEqual(argv[:3], ["docker", "run", "--rm"])
        self.assertIn(f"{root}:{root}:ro", argv)
        for assignment in ("HOME=/root", f"HERMES_HOME={hh.SMOKE_HOME}", "HERMES_DISABLE_LAZY_INSTALLS=1"):
            self.assertIn(assignment, argv)
        self.assertEqual(argv[argv.index("--network") + 1], "none")
        self.assertEqual(argv[-3:], commands["version"])
        self.assertIn("h1-env:1027-strace", argv)

    def test_smoke_main_fails_on_the_first_vm_symptoms(self):
        quiet = contextlib.ExitStack()
        quiet.enter_context(contextlib.redirect_stdout(io.StringIO()))
        quiet.enter_context(contextlib.redirect_stderr(io.StringIO()))
        self.addCleanup(quiet.close)
        outputs = iter([
            subprocess.CompletedProcess([], 0, "Hermes Agent v0.0.0\n", ""),
            subprocess.CompletedProcess([], 0, "", "hermes: source-update completion failed: an update is "
                                                   "still running\nModuleNotFoundError: No module named 'ruamel'"),
        ])
        argv = ["--image", "h1-env:1027-strace", "--root", self.root, "--binary", self.launcher]
        with patch.object(hh.subprocess, "run", side_effect=lambda *a, **k: next(outputs)) as run:
            self.assertEqual(hh._smoke_main(argv), 1)
        self.assertEqual(run.call_count, 2)
        ok = subprocess.CompletedProcess([], 0, "ok\n", "")
        with patch.object(hh.subprocess, "run", return_value=ok):
            self.assertEqual(hh._smoke_main(argv), 0)
        with patch.object(hh.subprocess, "run") as run:
            self.assertEqual(hh._smoke_main(["--image", "x", "--root", self.root, "--binary", "/usr/bin/true"]), 1)
        run.assert_not_called()


# What `hermes -z ... --usage-file F` writes at the pin (hermes_cli/oneshot.py
# _write_usage_file + _auxiliary_report): _USAGE_KEYS, failed, service_tier,
# auxiliary {_AUX_COUNTERS totals, total_tokens, by_task}, total_including_auxiliary.
REAL_USAGE = {
    "estimated_cost_usd": 0.1291, "cost_status": "estimated", "cost_source": "models.dev",
    "input_tokens": 2310, "output_tokens": 3120, "cache_read_tokens": 17159, "cache_write_tokens": 36214,
    "reasoning_tokens": 2720, "total_tokens": 5430, "api_calls": 3,
    "model": "claude-sonnet-5-5", "provider": "custom:proxy", "session_id": "20261103_101500_ab12cd",
    "completed": True, "partial": False, "interrupted": False, "turn_exit_reason": None,
    "failed": False, "service_tier": None,
    "auxiliary": {
        "api_calls": 1, "input_tokens": 262, "output_tokens": 14, "cache_read_tokens": 0,
        "cache_write_tokens": 0, "reasoning_tokens": 0, "estimated_cost_usd": 0.0047, "total_tokens": 276,
        "by_task": {"title_generation": {
            "api_calls": 1, "input_tokens": 262, "output_tokens": 14, "cache_read_tokens": 0,
            "cache_write_tokens": 0, "reasoning_tokens": 0, "estimated_cost_usd": 0.0047}},
    },
    "total_including_auxiliary": {"estimated_cost_usd": 0.1338, "total_tokens": 5706, "api_calls": 4},
}


class SummaryPlumbing(CellEnv):
    """main_calls / aux_calls / gateway_stop / hermes_extras reach summary.json."""

    def test_real_usage_file_shape_counts_main_and_title(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, "usage.json")
            path.write_text(json.dumps(REAL_USAGE, indent=2) + "\n")
            parsed = hh.parse_usage(str(path))
        self.assertEqual((parsed["main_calls"], parsed["aux_calls"], parsed["total_calls"]),
                         (3, {"title_generation": 1}, 4))
        self.assertEqual(parsed["total_calls"], REAL_USAGE["total_including_auxiliary"]["api_calls"])

    def test_settings_survive_run_cell_into_the_summary_fields(self):
        row, _, _ = self.run_cell(runner=FakeRunner(usage=REAL_USAGE))
        settings = row["harness_settings"]
        self.assertEqual((settings["main_calls"], settings["aux_calls"]), (3, {"title_generation": 1}))
        self.assertEqual(settings["gateway_stop"], {"stop_command": 0, "signalled": [], "survivors": []})
        self.assertEqual(settings["launch"]["extras"], ["all", "anthropic"])
        # run_cell carries the adapter's harness_settings onto the row (the docker path back).
        from obench.tests.test_phase_timing import TestPhaseTiming

        class _Fold(TestPhaseTiming):
            def runTest(self):
                pass
        fold = _Fold()
        fold.setUp()
        self.addCleanup(fold.tearDown)
        folded = fold._run_with_fakes(exec_used="docker", extra_result={"harness_settings": settings})
        self.assertEqual(folded["harness_settings"], settings)
        self.assertNotIn("harness_settings", fold._run_with_fakes())
        cell = Launcher().load()
        got = cell.cell_settings(folded, Path(self.ledger), "cellh")
        self.assertEqual((got["main_calls"], got["aux_calls"], got["gateway_stop"]["stop_command"],
                          got["launch"]["extras"]), (3, {"title_generation": 1}, 0, ["all", "anthropic"]))

    def test_local_cells_fall_back_to_the_settings_file(self):
        self.run_cell(runner=FakeRunner(usage=REAL_USAGE))
        cell = Launcher().load()
        got = cell.cell_settings({}, Path(self.ledger), "cellh")
        self.assertEqual(got["main_calls"], 3)
        self.assertEqual(cell.cell_settings({}, Path(self.ledger), "missing"), {})


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

        result = hh.stop_gateway(["/r/py", "/r/src/hermes"], "/tmp/h1", runner=runner,
                                 find_pids=lambda home: rounds.pop(0) if rounds else [],
                                 kill=lambda pid, sig: kills.append((pid, sig)), sleep=lambda s: None)
        self.assertEqual(calls, [(["/r/py", "/r/src/hermes", "gateway", "stop"], "/tmp/h1")])
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
        result = hh.stop_gateway(["/missing/python", "/r/src/hermes"], "/tmp/h1", runner=broken, find_pids=lambda h: [])
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

    def test_prep_script_prints_the_in_root_launcher_and_smokes_in_the_image(self):
        text = (ROOT / "data" / "hermes-harness-smoke" / "prep.sh").read_text()
        self.assertIn('BIN="$SRC/.hermes/bin/hermes"', text)
        self.assertNotIn('"$HOME/.local/bin/hermes"', text)
        self.assertIn('IMAGE="${OBENCH_CELL_IMAGE:-h1-env:1027-strace}"', text)
        self.assertIn('python3 -m obench.adapters.hermes_harness --image "$IMAGE" --root "$ROOT" --binary "$BIN"', text)
        self.assertLess(text.index("obench.adapters.hermes_harness --image"), text.index("export OBENCH_HERMES_BIN"))


if __name__ == "__main__":
    unittest.main()
