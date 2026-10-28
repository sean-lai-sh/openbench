"""Pi harness-comparison adapter: command, settings, totals, pin, docker env."""

import json
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from obench import docker_exec
from obench.adapters import pi
from obench.adapters import pi_harness


PIN = pi_harness.PIN
_ENV_KEYS = (
    "OBENCH_PI_HARNESS",
    "OBENCH_PI_VERTEX",
    "OBENCH_VERTEX_PROXY_URL",
    "OBENCH_VERTEX_CELL_ID",
    "OBENCH_VERTEX_LEDGER_DIR",
    "OBENCH_VERTEX_ROUTE_BY_REQUEST",
    "OBENCH_PI_BIN",
    "OBENCH_PI_PIN_FILE",
    "OBENCH_PI_MOUNT",
    "OBENCH_PI_SETTINGS_PATH",
    "PI_NODE_PREFIX",
    "OPENCODE_NODE_PREFIX",
    "OBENCH_OPENCODE_MOUNT",
    "BENCH_IN_CONTAINER",
    "OBENCH_DOCKER_NETWORK",
)


class _Env:
    def __init__(self, **updates):
        self.updates = updates
        self.saved = {}

    def __enter__(self):
        self.saved = {key: os.environ.get(key) for key in self.updates}
        for key, value in self.updates.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        return self

    def __exit__(self, *_exc):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _cleared():
    return {key: None for key in _ENV_KEYS}


def _binary(directory: Path, body: str) -> Path:
    path = directory / "pi"
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def _totals(all_calls=2, main_calls=1):
    return {
        "all": {
            "cache_read": 4, "cache_write": 3, "calls": all_calls,
            "input_uncached": 20, "output": 8,
        },
        "main": {
            "cache_read": 1, "cache_write": 1, "calls": main_calls,
            "input_uncached": 11, "output": 5,
        },
    }


class TestCommandAndSettings(unittest.TestCase):
    def test_command_keeps_shipped_defaults(self):
        cmd = pi_harness.build_command("/opt/pi", "fix it", "claude-sonnet-5-5", "/tmp/ext.mjs")
        self.assertEqual(cmd, [
            "/opt/pi", "-p", "fix it",
            "--mode", "json",
            "--no-approve",
            "-e", "/tmp/ext.mjs",
            "--provider", "anthropic",
            "--model", "claude-sonnet-5-5",
        ])
        banned = {"--thinking", "--tools", "--no-session", "--no-extensions", "--approve"}
        self.assertEqual(banned.intersection(cmd), set())

    def test_models_base_url_has_no_v1_suffix(self):
        self.assertEqual(
            pi_harness.cell_proxy_base("http://127.0.0.1:9/v1", "cell1"),
            "http://127.0.0.1:9/c/cell1",
        )
        self.assertEqual(
            pi_harness.cell_proxy_base("http://127.0.0.1:9/", "cell1"),
            "http://127.0.0.1:9/c/cell1",
        )
        body = json.loads(pi_harness.models_document("http://127.0.0.1:9/c/cell1", "claude-opus-5-5"))
        provider = body["providers"]["anthropic"]
        self.assertEqual(provider["baseUrl"], "http://127.0.0.1:9/c/cell1")
        self.assertFalse(provider["baseUrl"].endswith("/v1"))
        self.assertEqual(provider["api"], "anthropic-messages")
        self.assertEqual(provider["apiKey"], "proxy")
        model = provider["models"][0]
        self.assertEqual(model["id"], "claude-opus-5-5")
        self.assertTrue(model["reasoning"])
        self.assertEqual(model["contextWindow"], 1_000_000)
        self.assertEqual(model["maxTokens"], 128_000)

    def test_settings_log_section_four_defaults(self):
        settings = pi_harness.planned_settings(
            "claude-opus-5-5", 2400, "http://127.0.0.1:9/c/cell1", "/opt/pi", "/opt/pi.pin",
        )
        self.assertEqual(settings["pin"], PIN)
        self.assertFalse(settings["npm_tag_is_pin"])
        self.assertNotEqual(settings["npm_tag_v1_4_0"], PIN)
        wire = settings["wire"]
        self.assertEqual(wire["api"], "anthropic-messages")
        self.assertEqual(wire["path"], "/v1/messages")
        self.assertFalse(wire["openai_chat_completions"])
        self.assertFalse(wire["base_url"].endswith("/v1"))
        self.assertEqual(settings["thinking"]["level"], "medium")
        self.assertFalse(settings["thinking"]["argv_override"])
        self.assertIsNone(settings["temperature"])
        self.assertEqual(settings["tools"], ["read", "bash", "edit", "write"])
        self.assertFalse(settings["tools_argv_override"])
        self.assertIsNone(settings["shell_timeout_s"])
        self.assertEqual(settings["output_max_lines"], 2000)
        self.assertEqual(settings["output_max_bytes"], 50 * 1024)
        self.assertEqual(settings["read_max_lines"], 2000)
        self.assertEqual(settings["read_max_bytes"], 50 * 1024)
        self.assertEqual(settings["compaction"]["reserve_tokens"], 16384)
        self.assertEqual(settings["compaction"]["keep_recent_tokens"], 20000)
        self.assertTrue(settings["compaction"]["enabled"])
        self.assertFalse(settings["subagents"])
        self.assertEqual(settings["permission_mode"], "no-approve")
        self.assertEqual(settings["retry"]["max_retries"], 3)
        self.assertEqual(settings["retry"]["base_delay_ms"], 2000)
        self.assertEqual(settings["retry"]["provider_max_retries"], 0)
        self.assertEqual(settings["cell_cap_s"], 2400)

    def test_call_role_reads_system_text_only(self):
        self.assertEqual(
            pi_harness.call_role_for_system(
                "You are a context summarization assistant. Your task is to read"
            ),
            "side:summary",
        )
        self.assertEqual(
            pi_harness.call_role_for_system(
                "You are helping a user file a bug report about pi, the coding agent"
            ),
            "side:helper",
        )
        self.assertEqual(
            pi_harness.call_role_for_system("You are a sub-agent working on one file"),
            "side:subagent",
        )
        self.assertEqual(
            pi_harness.call_role_for_system("You are a coding agent.\nUse the tools."),
            "main",
        )
        source = pi_harness.extension_source()
        self.assertIn(pi_harness._SUMMARY_NEEDLE, source)
        self.assertIn(pi_harness._HELPER_NEEDLE, source)
        self.assertIn('message.role !== "system"', source)
        self.assertIn("body.system", source)
        self.assertIn(pi_harness.CALL_ROLE_HEADER, source)
        self.assertIn("export default function", source)

    def test_loopback_rewritten_only_inside_the_container(self):
        with _Env(BENCH_IN_CONTAINER=None, OBENCH_DOCKER_NETWORK=None):
            self.assertEqual(
                pi_harness.rewrite_loopback("http://127.0.0.1:9/c/abc"),
                "http://127.0.0.1:9/c/abc",
            )
        with _Env(BENCH_IN_CONTAINER="1", OBENCH_DOCKER_NETWORK=None):
            self.assertEqual(
                pi_harness.rewrite_loopback("http://127.0.0.1:9/c/abc"),
                "http://host.docker.internal:9/c/abc",
            )
            self.assertEqual(
                pi_harness.rewrite_loopback("http://localhost:9/c/abc"),
                "http://host.docker.internal:9/c/abc",
            )
            self.assertEqual(
                pi_harness.rewrite_loopback("http://10.1.2.3:9/c/abc"),
                "http://10.1.2.3:9/c/abc",
            )
        with _Env(BENCH_IN_CONTAINER="1", OBENCH_DOCKER_NETWORK="host"):
            self.assertEqual(
                pi_harness.rewrite_loopback("http://127.0.0.1:9/c/abc"),
                "http://127.0.0.1:9/c/abc",
            )


class TestTotals(unittest.TestCase):
    def test_side_is_all_minus_main(self):
        parsed = pi_harness.parse_proxy_totals(_totals())
        self.assertEqual(parsed["side"]["calls"], 1)
        self.assertEqual(parsed["side"]["input_uncached"], 9)
        self.assertEqual(parsed["side"]["output"], 3)
        self.assertEqual(parsed["side"]["cache_read"], 3)
        self.assertEqual(parsed["side"]["cache_write"], 2)
        self.assertEqual(parsed["all"]["calls"], 2)
        self.assertEqual(parsed["main"]["calls"], 1)

    def test_main_larger_than_all_is_rejected(self):
        with self.assertRaises(ValueError):
            pi_harness.parse_proxy_totals(_totals(all_calls=1, main_calls=2))

    def test_bool_and_missing_bucket_are_rejected(self):
        payload = _totals()
        payload["all"]["calls"] = True
        with self.assertRaises(ValueError):
            pi_harness.parse_proxy_totals(payload)
        missing = _totals()
        del missing["main"]
        with self.assertRaises(ValueError):
            pi_harness.parse_proxy_totals(missing)


class TestRun(unittest.TestCase):
    def _stamp(self, directory: Path, text: str) -> Path:
        path = directory / "pin.txt"
        path.write_text(text + "\n", encoding="utf-8")
        return path

    def test_opus_without_comparison_env_stays_unsupported(self):
        with _Env(**_cleared()):
            result = pi.run("task", "/tmp", "claude-opus-5-5", 10)
        self.assertFalse(result["completed"])
        self.assertIn("unsupported-model", result["error"])
        self.assertIn("claude-opus-5-5", result["error"])

    def test_pin_mismatch_does_not_launch(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            marker = root / "launched"
            binary = _binary(root, textwrap.dedent(f"""\
                #!/usr/bin/env python3
                from pathlib import Path
                Path({str(marker)!r}).write_text("ran")
            """))
            stamp = self._stamp(root, "not-the-pin")
            updates = _cleared()
            updates.update({
                "OBENCH_PI_HARNESS": "1",
                "OBENCH_VERTEX_PROXY_URL": "http://127.0.0.1:9",
                "OBENCH_VERTEX_CELL_ID": "cell1",
                "OBENCH_VERTEX_LEDGER_DIR": str(root),
                "OBENCH_PI_BIN": str(binary),
                "OBENCH_PI_PIN_FILE": str(stamp),
            })
            with _Env(**updates):
                result = pi.run("task", "/tmp", "claude-sonnet-5-5", 10)
            self.assertFalse(result["completed"])
            self.assertIn(PIN, result["error"])
            self.assertFalse(marker.exists())
            self.assertIsNone(result["cmd"])

    def test_cell_logs_settings_and_parses_totals(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            capture = root / "capture.json"
            binary = _binary(root, textwrap.dedent(f"""\
                #!/usr/bin/env python3
                import json, os, sys
                from pathlib import Path
                agent = Path(os.environ["PI_CODING_AGENT_DIR"])
                files = {{path.name: path.read_text(encoding="utf-8") for path in agent.iterdir()}}
                ext = ""
                if "-e" in sys.argv:
                    ext = Path(sys.argv[sys.argv.index("-e") + 1]).read_text(encoding="utf-8")
                Path({str(capture)!r}).write_text(json.dumps({{
                    "argv": sys.argv, "files": files, "ext": ext,
                }}))
                usage = {{
                    "input": 11, "cacheRead": 1, "cacheWrite": 1,
                    "output": 5, "reasoning": 1, "totalTokens": 18,
                }}
                print(json.dumps({{
                    "type": "turn_end",
                    "message": {{
                        "role": "assistant",
                        "content": [{{"type": "text", "text": "done"}}],
                        "usage": usage,
                    }},
                }}))
                print(json.dumps({{"type": "compaction_end", "aborted": False, "reason": "threshold"}}))
                print(json.dumps({{"type": "compaction_end", "aborted": True, "reason": "threshold"}}))
            """))
            stamp = self._stamp(root, PIN)
            (root / "cell1.totals.json").write_text(
                json.dumps(_totals()) + "\n", encoding="utf-8",
            )
            settings_path = root / "settings.json"
            (root / "work").mkdir()
            updates = _cleared()
            updates.update({
                "OBENCH_PI_HARNESS": "1",
                "OBENCH_VERTEX_PROXY_URL": "http://127.0.0.1:9/v1",
                "OBENCH_VERTEX_CELL_ID": "cell1",
                "OBENCH_VERTEX_LEDGER_DIR": str(root),
                "OBENCH_PI_BIN": str(binary),
                "OBENCH_PI_PIN_FILE": str(stamp),
                "OBENCH_PI_SETTINGS_PATH": str(settings_path),
            })
            with _Env(**updates):
                self.assertEqual(pi._comparison_env_set(), pi_harness.comparison_requested())
                result = pi.run("fix the test", str(root / "work"), "claude-sonnet-5-5", 2400)
            self.assertTrue(result["completed"], result.get("error"))
            self.assertIsNone(result["error"])
            self.assertEqual(result["tokens_output"], 5)
            self.assertEqual(result["model_context_window"], 1_000_000)
            captured = json.loads(capture.read_text(encoding="utf-8"))
            self.assertEqual(captured["argv"][1:7], [
                "-p", "fix the test", "--mode", "json", "--no-approve", "-e",
            ])
            self.assertTrue(captured["argv"][7].endswith("obench-call-role.mjs"))
            self.assertEqual(captured["argv"][-4:], [
                "--provider", "anthropic", "--model", "claude-sonnet-5-5",
            ])
            self.assertNotIn("--thinking", captured["argv"])
            self.assertNotIn("--tools", captured["argv"])
            self.assertNotIn("--no-extensions", captured["argv"])
            self.assertNotIn("settings.json", captured["files"])
            models = json.loads(captured["files"]["models.json"])
            base = models["providers"]["anthropic"]["baseUrl"]
            self.assertEqual(base, "http://127.0.0.1:9/c/cell1")
            self.assertFalse(base.endswith("/v1"))
            self.assertIn(pi_harness.CALL_ROLE_HEADER, captured["ext"])
            self.assertIn("message.role !== \"system\"", captured["ext"])
            logged = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(logged["pin"], PIN)
            self.assertFalse(logged["wire"]["openai_chat_completions"])
            self.assertEqual(logged["wire"]["path"], "/v1/messages")
            self.assertIsNone(logged["shell_timeout_s"])
            self.assertEqual(logged["permission_mode"], "no-approve")
            self.assertEqual(logged["compactions_fired"], 1)
            self.assertEqual(logged["turns"], 1)
            self.assertEqual(logged["proxy_totals"]["side"]["calls"], 1)
            self.assertEqual(logged["side_calls"], 1)
            self.assertIsNone(logged["proxy_totals_error"])
            self.assertEqual(result["harness_settings"]["proxy_totals"]["main"]["calls"], 1)

    def test_vertex_spec_wins_over_the_comparison_env(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            launched = root / "which"
            vertex_dir = root / "ab"
            compare_dir = root / "cmp"
            vertex_dir.mkdir()
            compare_dir.mkdir()
            vertex_bin = _binary(vertex_dir, textwrap.dedent(f"""\
                #!/usr/bin/env python3
                import json
                from pathlib import Path
                Path({str(launched)!r}).write_text("vertex")
                print(json.dumps({{"type": "turn_end", "message": {{"role": "assistant", "usage": {{
                    "input": 1, "cacheRead": 0, "cacheWrite": 0, "output": 1,
                    "reasoning": 0, "totalTokens": 2,
                }}}}}}))
            """))
            compare_bin = _binary(compare_dir, textwrap.dedent(f"""\
                #!/usr/bin/env python3
                from pathlib import Path
                Path({str(launched)!r}).write_text("comparison")
            """))
            stamp = self._stamp(root, PIN)
            spec = {
                "bin": str(vertex_bin),
                "agent_env": "PI_CODING_AGENT_DIR",
                "home_dir": ".pi",
                "models_filename": "models.json",
                "models_body": '{"providers":{"vertex-anthropic":{"baseUrl":"http://127.0.0.1:9"}}}\n',
                "extra_args": ["--no-session"],
                "provider": "vertex-anthropic",
                "model_id": "claude-opus-5-5",
            }
            updates = _cleared()
            updates.update({
                "OBENCH_PI_VERTEX": json.dumps(spec),
                "OBENCH_PI_HARNESS": "1",
                "OBENCH_VERTEX_PROXY_URL": "http://127.0.0.1:9",
                "OBENCH_VERTEX_CELL_ID": "cell1",
                "OBENCH_PI_BIN": str(compare_bin),
                "OBENCH_PI_PIN_FILE": str(stamp),
            })
            with _Env(**updates):
                result = pi.run("task", "/tmp", "claude-opus-5-5", 10)
            self.assertTrue(result["completed"], result.get("error"))
            self.assertEqual(launched.read_text(encoding="utf-8"), "vertex")
            self.assertIn("--provider", result["cmd"])
            self.assertEqual(result["cmd"][result["cmd"].index("--provider") + 1], "vertex-anthropic")
            self.assertIn("--no-session", result["cmd"])


class TestDockerForwarding(unittest.TestCase):
    def test_comparison_env_is_off_unless_asked(self):
        with _Env(**_cleared()):
            cmd = docker_exec.build_docker_cmd(
                harness="pi", workdir="/tmp/wd", model="claude-opus-5-5",
                timeout_s=2400, adapters_dir="/repo/obench/adapters",
                image="openbench-harness:latest", instruction_path="/tmp/instr",
            )
        joined = " ".join(cmd)
        self.assertNotIn("OBENCH_VERTEX_PROXY_URL", joined)
        self.assertNotIn("host.docker.internal", joined)
        self.assertNotIn("OBENCH_PI_BIN", joined)

    def test_comparison_env_is_forwarded_for_pi_only(self):
        with tempfile.TemporaryDirectory() as mount:
            updates = _cleared()
            updates.update({
                "OBENCH_PI_HARNESS": "1",
                "OBENCH_VERTEX_PROXY_URL": "http://127.0.0.1:9",
                "OBENCH_VERTEX_CELL_ID": "cell1",
                "OBENCH_PI_BIN": "/cache/pi",
                "OBENCH_PI_PIN_FILE": "/cache/pi.pin",
                "OBENCH_PI_MOUNT": mount,
            })
            with _Env(**updates):
                cmd = docker_exec.build_docker_cmd(
                    harness="pi", workdir="/tmp/wd", model="claude-sonnet-5-5",
                    timeout_s=2400, adapters_dir="/repo/obench/adapters",
                    image="openbench-harness:latest", instruction_path="/tmp/instr",
                )
                other = docker_exec.build_docker_cmd(
                    harness="codex", workdir="/tmp/wd", model="gpt-5.5-medium",
                    timeout_s=2400, adapters_dir="/repo/obench/adapters",
                    image="openbench-harness:latest", instruction_path="/tmp/instr",
                )
            self.assertIn("--add-host=host.docker.internal:host-gateway", cmd)
            self.assertIn("--add-host=api.anthropic.com:0.0.0.0", cmd)
            self.assertIn("-e", cmd)
            self.assertIn("OBENCH_DOCKER_NETWORK=bridge", cmd)
            mount_abs = os.path.abspath(mount)
            self.assertIn(f"{mount_abs}:{docker_exec.PI_CACHE_CONTAINER}:ro", cmd)
            self.assertNotIn(f"{mount_abs}:{mount_abs}:ro", cmd)
            for name in (
                "OBENCH_PI_HARNESS", "OBENCH_VERTEX_PROXY_URL", "OBENCH_VERTEX_CELL_ID",
                "OBENCH_PI_BIN", "OBENCH_PI_PIN_FILE", "OBENCH_PI_MOUNT",
            ):
                self.assertIn(name, cmd)
                index = cmd.index(name)
                self.assertEqual(cmd[index - 1], "-e")
                self.assertNotIn("=", cmd[index])
            self.assertNotIn("http://127.0.0.1:9", cmd)
            self.assertNotIn("OBENCH_VERTEX_PROXY_URL", other)

    def test_host_network_keeps_loopback_and_skips_the_bridge_hosts(self):
        updates = _cleared()
        updates.update({
            "OBENCH_PI_HARNESS": "1",
            "OBENCH_VERTEX_PROXY_URL": "http://127.0.0.1:9",
            "OBENCH_VERTEX_CELL_ID": "cell1",
        })
        with _Env(**updates):
            cmd = docker_exec.build_docker_cmd(
                harness="pi", workdir="/tmp/wd", model="claude-sonnet-5-5",
                timeout_s=2400, adapters_dir="/repo/obench/adapters",
                image="openbench-harness:latest", instruction_path="/tmp/instr",
                extra_docker_args=["--network", "host"],
            )
        self.assertNotIn("--add-host=host.docker.internal:host-gateway", cmd)
        self.assertNotIn("--add-host=api.anthropic.com:0.0.0.0", cmd)
        self.assertIn("OBENCH_DOCKER_NETWORK=host", cmd)
        self.assertIn("--network", cmd)
        self.assertEqual(cmd[cmd.index("--network") + 1], "host")

    def test_cached_wrapper_paths_are_the_container_mounts(self):
        with tempfile.TemporaryDirectory() as cache, tempfile.TemporaryDirectory() as node:
            binary = Path(cache) / "bin" / "pi" / "sha" / "pi"
            binary.parent.mkdir(parents=True)
            binary.write_text("#!/bin/sh\n", encoding="utf-8")
            pin = Path(str(binary) + ".pin")
            pin.write_text("pin\n", encoding="utf-8")
            updates = _cleared()
            updates.update({
                "OBENCH_PI_HARNESS": "1",
                "OBENCH_VERTEX_PROXY_URL": "http://127.0.0.1:9",
                "OBENCH_PI_BIN": str(binary),
                "OBENCH_PI_PIN_FILE": str(pin),
                "OBENCH_PI_MOUNT": cache,
                "PI_NODE_PREFIX": node,
            })
            with _Env(**updates):
                cmd = docker_exec.build_docker_cmd(
                    harness="pi", workdir="/tmp/wd", model="claude-sonnet-5-5",
                    timeout_s=2400, adapters_dir="/repo/obench/adapters",
                    image="openbench-harness:latest", instruction_path="/tmp/instr",
                )
        cache_abs = os.path.abspath(cache)
        node_abs = os.path.abspath(node)
        self.assertIn(f"{cache_abs}:/h1/pi-src:ro", cmd)
        self.assertIn(f"{node_abs}:/opt/node-v22.19.0:ro", cmd)
        self.assertIn("PATH=/opt/node-v22.19.0/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", cmd)
        rel_bin = Path(binary).relative_to(cache).as_posix()
        rel_pin = Path(pin).relative_to(cache).as_posix()
        self.assertIn(f"OBENCH_PI_BIN=/h1/pi-src/{rel_bin}", cmd)
        self.assertIn(f"OBENCH_PI_PIN_FILE=/h1/pi-src/{rel_pin}", cmd)
        self.assertNotIn(cache_abs, " ".join(item for item in cmd if item.startswith("OBENCH_PI_BIN=")))

    def test_rewrite_loopback_runs_without_thesis(self):
        script = textwrap.dedent(
            """
            import importlib.abc, os, sys

            class Block(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path, target=None):
                    if fullname == "thesis" or fullname.startswith("thesis."):
                        raise ModuleNotFoundError(fullname)
                    return None

            sys.meta_path.insert(0, Block())
            for name in list(sys.modules):
                if name == "thesis" or name.startswith("thesis."):
                    del sys.modules[name]
            os.environ["BENCH_IN_CONTAINER"] = "1"
            os.environ.pop("OBENCH_DOCKER_NETWORK", None)
            from obench.adapters.pi_harness import rewrite_loopback
            from obench.adapters.opencode import reachable_proxy_base
            pi_url = rewrite_loopback("http://127.0.0.1:9/c/abc")
            oc_url = reachable_proxy_base("http://127.0.0.1:9/v1")
            assert pi_url == "http://host.docker.internal:9/c/abc", pi_url
            assert oc_url == "http://host.docker.internal:9/v1", oc_url
            print("ok")
            """
        )
        root = Path(__file__).resolve().parents[2]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
        env.pop("BENCH_IN_CONTAINER", None)
        env.pop("OBENCH_DOCKER_NETWORK", None)
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, env=env, cwd=str(root),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("ok", proc.stdout)


if __name__ == "__main__":
    unittest.main()
