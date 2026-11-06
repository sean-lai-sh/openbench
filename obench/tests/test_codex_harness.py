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


def _usage(inp, cached, out):
    return {"input_tokens": inp, "cached_input_tokens": cached, "output_tokens": out,
            "reasoning_output_tokens": 0, "total_tokens": inp + out}


def rollout_lines(per_call):
    """A Codex 0.144.5 rollout: one token_count event per model response, plus
    a rate-limit-only event (info null) and a repeated total, neither a call."""
    lines = [{"timestamp": "t0", "type": "session_meta", "payload": {"id": "s1"}},
             {"timestamp": "t0", "type": "event_msg", "payload": {"type": "token_count", "info": None,
                                                                   "rate_limits": {}}}]
    total = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0,
             "reasoning_output_tokens": 0, "total_tokens": 0}
    for last in per_call:
        total = {k: total[k] + last[k] for k in total}
        info = {"total_token_usage": dict(total), "last_token_usage": last, "model_context_window": 200000}
        lines.append({"timestamp": "t", "type": "event_msg", "payload": {"type": "token_count", "info": info}})
        lines.append({"timestamp": "t", "type": "response_item", "payload": {"type": "message"}})
    lines.append(dict(lines[-2]))  # Codex re-emits the last count with an unchanged total
    return "\n".join(json.dumps(line) for line in lines) + "\n"


CALLS = [_usage(11346, 0, 600), _usage(13001, 11346, 700), _usage(13558, 13001, 500), _usage(13789, 13558, 578)]


class FakeRunner:
    def __init__(self, version="codex-cli 0.144.5", returncode=0, stdout=TURN_JSONL, timeout=False, rollout=None):
        self.version = version
        self.returncode = returncode
        self.stdout = stdout
        self.timeout = timeout
        self.rollout = rollout
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        if cmd[1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=self.version + "\n", stderr="")
        if self.rollout is not None:
            day = Path(kwargs["env"]["CODEX_HOME"]) / "sessions" / "2026" / "11" / "03"
            day.mkdir(parents=True, exist_ok=True)
            (day / "rollout-2026-11-03T10-00-00-abc.jsonl").write_text(self.rollout)
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
            "OBENCH_CODEX_HARNESS": "1",
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
        for name in ("BENCH_IN_CONTAINER", "OBENCH_DOCKER_NETWORK", "OBENCH_CODEX_SETTINGS_PATH"):
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

    def test_no_reasoning_override_codex_sends_no_thinking(self):
        """AD2-codex-reasoning is off: stock Codex sends no `reasoning` for a
        Claude id, matching the OpenCode thinking reference."""
        joined = " ".join(self.cmd())
        self.assertNotIn("model_supports_reasoning_summaries", joined)
        self.assertNotIn("model_reasoning_summary", joined)
        self.assertEqual(ch.THINKING_REFERENCE, "opencode")

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
        self.assertEqual(row["turns"], 1)  # no rollout: falls back to turn.completed
        self.assertEqual(row["model_context_window"], 200_000)
        self.assertEqual(row["adapter_fixes"], ["AD1-codex-ctx"])
        self.assertNotIn("AD2-codex-reasoning", row["harness_settings"]["adapter_fixes"])
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


class TraceTests(CellEnv):
    """Smoke at ddd5096d: trace_requests=1, untraced_requests=3. Every model
    call must be traced, as it is for Pi (one turn_end per call)."""

    def test_rollout_token_counts_give_one_trace_entry_per_model_call(self):
        from thesis.ab.run_ab import harness_trace_requests
        self.write_totals()
        row = ch.run("fix", self.workdir, "claude-sonnet-5-5", 600, runner=FakeRunner(rollout=rollout_lines(CALLS)))
        self.assertEqual(row["turns"], 4)
        self.assertEqual(row["model_calls"], 4)
        self.assertEqual(row["codex_turn_events"], 1)
        self.assertEqual(row["usage_raw"], CALLS)
        self.assertEqual(harness_trace_requests(row), 4)
        settings = row["harness_settings"]
        self.assertEqual((settings["turns"], settings["model_calls"], settings["codex_turn_events"]), (4, 4, 1))

    def test_trace_matches_a_four_request_ledger(self):
        from thesis.ab.run_ab import attach_proxy_trace
        row = ch.run("fix", self.workdir, "claude-sonnet-5-5", 600, runner=FakeRunner(rollout=rollout_lines(CALLS)))
        ledger = [{"usage": {"input_tokens": 1}, "upstream_model": "claude-sonnet-5-5",
                   "requested_model": "claude-sonnet-5-5", "endpoint_location": "global"} for _ in CALLS]
        attach_proxy_trace(row, ledger, "claude-sonnet-5-5", ledger_present=True)
        self.assertEqual(row["trace_requests"], 4)
        self.assertEqual(row["untraced_requests"], 0)

    def test_rollout_parser_ignores_noise_and_reads_every_file(self):
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        self.assertEqual(ch.rollout_model_calls(home), [])
        day = Path(home, "sessions", "2026", "11", "03")
        day.mkdir(parents=True)
        (day / "rollout-a.jsonl").write_text(rollout_lines(CALLS[:2]) + "not json\n")
        (day / "rollout-b.jsonl").write_text(rollout_lines(CALLS[2:]))
        (day / "other.jsonl").write_text(rollout_lines(CALLS))
        self.assertEqual(ch.rollout_model_calls(home), CALLS)

    def test_timeout_still_reports_the_calls_made(self):
        row = ch.run("fix", self.workdir, "claude-sonnet-5-5", 60,
                     runner=FakeRunner(timeout=True, rollout=rollout_lines(CALLS[:2])))
        self.assertEqual(row["failure_class"], "timeout")
        self.assertEqual(row["turns"], 2)
        self.assertEqual(row["model_calls"], 2)


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

    def test_proxy_url_without_the_flag_does_not_route(self):
        """A shared OBENCH_VERTEX_PROXY_URL (e.g. from a Pi run) alone keeps the stock path."""
        with patch.dict(os.environ, {"OBENCH_CODEX_HARNESS": ""}):
            self.assertTrue(os.environ["OBENCH_VERTEX_PROXY_URL"])
            self.assertFalse(codex_adapter._comparison_env_set())
            self.assertFalse(ch.comparison_requested())
            with patch.object(ch, "run") as harness_run, \
                    patch.object(codex_adapter.subprocess, "run") as stock_run:
                row = codex_adapter.run("fix", self.workdir, "claude-sonnet-5-5", 60)
            harness_run.assert_not_called()
            stock_run.assert_not_called()  # stock Codex has no Claude model: unsupported, no spawn
            self.assertFalse(row["completed"])
            # Calling the harness directly without the flag fails closed too.
            direct = ch.run("fix", self.workdir, "claude-sonnet-5-5", 60, runner=FakeRunner())
            self.assertEqual(direct["error"], "Codex harness comparison needs OBENCH_CODEX_HARNESS=1")

    def test_flag_and_proxy_url_route_to_the_harness(self):
        self.assertTrue(codex_adapter._comparison_env_set())
        self.assertTrue(ch.comparison_requested())
        with patch.object(ch, "run", return_value={"completed": True, "via": "harness"}) as harness_run:
            row = codex_adapter.run("fix", self.workdir, "claude-sonnet-5-5", 60)
        self.assertEqual(row["via"], "harness")
        harness_run.assert_called_once()
        runner = FakeRunner()
        routed = ch.run("fix", self.workdir, "claude-sonnet-5-5", 60, runner=runner)
        self.assertTrue(routed["completed"])
        self.assertIn("/c/cellabc/v1", " ".join(runner.calls[-1][0]))

    def test_flag_without_proxy_url_fails_clearly(self):
        with patch.dict(os.environ, {"OBENCH_VERTEX_PROXY_URL": ""}):
            self.assertTrue(ch.comparison_requested())
            runner = FakeRunner()
            row = ch.run("fix", self.workdir, "claude-sonnet-5-5", 60, runner=runner)
        self.assertFalse(row["completed"])
        self.assertEqual(row["error"], "Codex harness comparison: OBENCH_CODEX_HARNESS=1 is set but "
                                       "OBENCH_VERTEX_PROXY_URL (the proxy address) is missing")
        self.assertEqual(runner.calls, [])  # no --version, no model call

    def test_flag_values(self):
        for value in ("1", "true", "YES", "on"):
            with patch.dict(os.environ, {"OBENCH_CODEX_HARNESS": value}):
                self.assertTrue(ch.comparison_requested(), value)
                self.assertTrue(codex_adapter._comparison_env_set(), value)
        for value in ("", "0", "false", "off"):
            with patch.dict(os.environ, {"OBENCH_CODEX_HARNESS": value}):
                self.assertFalse(ch.comparison_requested(), value)
                self.assertFalse(codex_adapter._comparison_env_set(), value)


class DockerArgsTests(CellEnv):
    def test_codex_cells_get_env_mount_and_sinkholes(self):
        with patch("thesis.ab.proxy_bridge.shared_proxy_port", return_value=4567):
            args = docker_exec._proxy_bridge_docker_args("codex", [])
        self.assertIn("OBENCH_CODEX_HARNESS", args)
        self.assertIn("OBENCH_VERTEX_CELL_ID", args)
        self.assertIn("/opt/codex:/opt/openbench-codex:ro", args)
        self.assertIn("OBENCH_CODEX_BIN=/opt/openbench-codex/codex", args)
        self.assertIn("--add-host=api.openai.com:0.0.0.0", args)
        self.assertIn("--add-host=chatgpt.com:0.0.0.0", args)
        self.assertIn("--add-host=api.anthropic.com:0.0.0.0", args)
        self.assertNotIn("OPENAI_API_KEY", args)

    def test_stock_codex_cells_are_untouched(self):
        with patch.dict(os.environ, {"OBENCH_CODEX_HARNESS": "", "OBENCH_VERTEX_PROXY_URL": ""}):
            self.assertEqual(docker_exec._proxy_bridge_docker_args("codex", []), [])
        # A Pi run's shared proxy URL alone does not make a codex cell a comparison cell.
        with patch.dict(os.environ, {"OBENCH_CODEX_HARNESS": ""}):
            self.assertEqual(docker_exec._proxy_bridge_docker_args("codex", []), [])


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

    def evidence_rows(self, cache_reads=(0, 9000, 9500, 9800), sent="none", tools=(1000, 1000)):
        rows = []
        for i, read in enumerate(cache_reads, 1):
            rows.append({"usage": {"input_tokens": 1, "output_tokens_details": {"thinking_tokens": 0}},
                         "cache_read": read, "thinking_sent": sent,
                         "cc_identity_stripped": {"responses": {
                             "responses_raw_request_file": f"c.responses/{i:04d}.request.json",
                             "responses_system_bytes": 9000, "responses_raw_system_bytes": 9000,
                             "responses_tools_bytes": tools[0], "responses_raw_tools_bytes": tools[1]}}})
        return rows

    def test_smoke_evidence_all_pass(self):
        cell = self.load()
        rows = self.evidence_rows()
        evidence = cell.smoke_evidence({"trace_requests": 4, "untraced_requests": 0}, rows,
                                       {"pi": ["adaptive"], "opencode": ["none"]})
        self.assertEqual({k: v["pass"] for k, v in evidence.items()},
                         {"1_traced": True, "2_cache_read": True, "3_thinking_sent": True, "4_prompt_bytes": True})
        self.assertEqual(evidence["2_cache_read"]["per_call"], [0, 9000, 9500, 9800])
        self.assertEqual(evidence["3_thinking_sent"]["reference_arm"], "opencode")
        self.assertEqual(evidence["3_thinking_sent"]["matches"], {"pi": False, "opencode": True})
        self.assertEqual(evidence["4_prompt_bytes"]["per_call"][0]["raw_request_file"], "c.responses/0001.request.json")

    def test_strict_thinking_fails_codex_on_server_thinking_tokens(self):
        """The ddd5096d Codex smoke: thinking_sent=none, 1051 server thinking tokens on call 1."""
        cell = self.load()
        rows = self.evidence_rows()
        rows[0]["usage"]["output_tokens_details"]["thinking_tokens"] = 1051
        check = cell.smoke_evidence({"trace_requests": 4, "untraced_requests": 0}, rows,
                                    {"pi": ["adaptive"], "opencode": ["none"]})["3_thinking_sent"]
        self.assertTrue(check["matches"]["opencode"])  # same shape; still matches the reference value
        self.assertFalse(check["pass"])
        self.assertEqual(check["failing_calls"], [1])

    def test_smoke_evidence_reports_each_failure(self):
        cell = self.load()
        evidence = cell.smoke_evidence(
            {"trace_requests": 1, "untraced_requests": 3},
            self.evidence_rows(cache_reads=(0, 0, 0, 0), sent="adaptive", tools=(1100, 1000)),
            {"pi": ["adaptive"], "opencode": ["none"]})
        self.assertFalse(evidence["1_traced"]["pass"])
        self.assertFalse(evidence["2_cache_read"]["pass"])
        self.assertEqual(evidence["3_thinking_sent"]["matches"], {"pi": True, "opencode": False})
        self.assertFalse(evidence["3_thinking_sent"]["pass"])  # OpenCode is the reference
        self.assertEqual(evidence["4_prompt_bytes"]["per_call"][0]["tools_delta"], 0.1)
        self.assertFalse(evidence["4_prompt_bytes"]["pass"])

    def test_reference_thinking_comes_from_the_196_ledgers(self):
        """Pi and OpenCode recorded different thinking_sent for Sonnet 5.5 in #196."""
        cell = self.load()
        self.assertEqual(cell.reference_thinking(ROOT, "claude-sonnet-5-5"),
                         {"pi": ["adaptive"], "opencode": ["none"]})

    def test_launcher_defaults_match_the_other_arms(self):
        cell = self.load()
        self.assertEqual(cell.MODEL_ID, "claude-sonnet-5-5")
        self.assertEqual(cell.TIMEOUT_S, 2400)
        self.assertEqual(cell.TASK, "polyglot-rust-c")
        args = cell.argument_parser().parse_args(["--out", "/tmp/o"])
        self.assertTrue(args.require_model_match)


if __name__ == "__main__":
    unittest.main()
