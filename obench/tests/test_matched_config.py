"""Matched Pi vs OpenCode pair: 200K context and explicit thinking off.

The profile is opt-in (``OBENCH_MATCHED_CONFIG`` / ``run_ab --matched-config``).
Opus 5.5 and Sonnet 5.5 configs and request bodies outside that flag stay
byte-for-byte the historical documents.
"""

from __future__ import annotations

import json
import os
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from obench.adapters import opencode, pi_harness
from thesis.ab.cell_fixtures import apply_matched_pair_config
from thesis.ab.compat import anthropic_proxy_config
from thesis.ab.models_config import model_document
from thesis.ab.proxy_bridge import read_proxy_observed
from thesis.ab.prs import parse_prs, select_prs
from thesis.ab.run_ab import attach_thinking, drive
from thesis.ab.vertex_anthropic_proxy import (
    apply_disabled_thinking,
    canonical_object_json,
    classify_thinking,
    matched_opus_effort,
    matched_request_thinking,
    server_thinking_tokens,
    start_proxy,
    wire_bytes_identical,
)

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = Path(__file__).resolve().parent / "fixtures" / "matched-config"
FIXTURE = ROOT / "thesis" / "ab" / "fixtures" / "opencode-harness-prs.csv"
ENV = "OBENCH_MATCHED_CONFIG"


def _load_smoke(relative: str, name: str):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Env:
    def __init__(self, **updates):
        self.updates = updates
        self.saved = {}

    def __enter__(self):
        for key, value in self.updates.items():
            self.saved[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        return self

    def __exit__(self, *_args):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class _Upstream(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):  # noqa: N802 - stdlib name
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        self.server.seen.append(raw)
        usage = self.server.usages.pop(0)
        body = json.dumps({"id": "msg", "usage": usage}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return


def _listen(usages):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Upstream)
    httpd.seen = []
    httpd.usages = list(usages)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address
    return httpd, thread, f"http://{host}:{port}"


def _post(url, body):
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, response.read()


class HistoricalConfigTests(unittest.TestCase):
    def test_pi_models_and_argv_match_the_historical_bytes(self):
        with _Env(**{ENV: None}):
            opus = pi_harness.models_document(
                "http://127.0.0.1:9/c/cell1", "claude-opus-5-5", matched=False,
            )
            sonnet = pi_harness.models_document(
                "http://127.0.0.1:9/c/cell1", "claude-sonnet-5-5", matched=False,
            )
            cmd = pi_harness.build_command(
                "/opt/pi", "fix it", "claude-sonnet-5-5", "/tmp/ext.mjs", matched=False,
            )
        self.assertEqual(opus, (GOLDEN / "pi-opus.json").read_text(encoding="utf-8"))
        self.assertEqual(sonnet, (GOLDEN / "pi-sonnet.json").read_text(encoding="utf-8"))
        self.assertEqual(cmd, [
            "/opt/pi", "-p", "fix it", "--mode", "json", "--no-approve", "-e",
            "/tmp/ext.mjs", "--provider", "anthropic", "--model", "claude-sonnet-5-5",
        ])
        self.assertNotIn("--thinking", cmd)
        self.assertNotIn("200000", opus)
        self.assertNotIn("200000", sonnet)

    def test_opencode_and_proxy_configs_match_the_historical_bytes(self):
        smoke = _load_smoke("data/opencode-harness-smoke/cell.py", "oc_matched_hist")
        with _Env(**{ENV: None}):
            pinned = smoke.comparison_config("http://127.0.0.1:9/v1")
            plain = anthropic_proxy_config("http://127.0.0.1:9/v1", include_endpoint=True)
        self.assertEqual(
            json.dumps(pinned, indent=2) + "\n",
            (GOLDEN / "oc.json").read_text(encoding="utf-8"),
        )
        self.assertEqual(
            json.dumps(plain, indent=2) + "\n",
            (GOLDEN / "anth.json").read_text(encoding="utf-8"),
        )
        self.assertEqual(
            pinned["provider"]["anthropic"]["models"]["claude-sonnet-5-5"]["limit"]["context"],
            1000000,
        )
        self.assertNotIn("options", pinned["provider"]["anthropic"]["models"]["claude-sonnet-5-5"])
        self.assertEqual(opencode.comparison_variant("claude-opus-5-5"), "medium")
        self.assertEqual(opencode.comparison_variant("claude-opus-4-8"), "medium")

    def test_unset_flag_does_not_rewrite_the_request(self):
        body = {
            "model": "claude-opus-5-5",
            "max_tokens": 16,
            "messages": [{"role": "user", "content": "hi"}],
        }
        before = json.dumps(body)
        with _Env(**{ENV: None}):
            self.assertFalse(apply_disabled_thinking(body))
        self.assertEqual(json.dumps(body), before)
        self.assertNotIn("thinking", body)
        self.assertEqual(classify_thinking(body), "none")
        # A reasoning counter is not the server thinking count.
        self.assertIsNone(server_thinking_tokens({
            "output_tokens": 9,
            "reasoning_tokens": 9,
            "output_tokens_details": {"reasoning_tokens": 9},
        }))


class MatchedConfigTests(unittest.TestCase):
    def test_pi_uses_200k_and_thinking_off(self):
        with _Env(**{ENV: "1"}):
            opus = json.loads(pi_harness.models_document(
                "http://127.0.0.1:9/c/cell1", "claude-opus-5-5",
            ))
            sonnet = json.loads(pi_harness.models_document(
                "http://127.0.0.1:9/c/cell1", "claude-sonnet-5-5",
            ))
            cmd = pi_harness.build_command(
                "/opt/pi", "fix it", "claude-sonnet-5-5", "/tmp/ext.mjs",
            )
            settings = pi_harness.planned_settings(
                "claude-sonnet-5-5", 2400, "http://127.0.0.1:9/c/cell1",
                "/opt/pi", "/opt/pi.pin",
            )
        for document, model_id in ((opus, "claude-opus-5-5"), (sonnet, "claude-sonnet-5-5")):
            model = document["providers"]["anthropic"]["models"][0]
            self.assertEqual(model["id"], model_id)
            self.assertEqual(model["contextWindow"], 200000)
            self.assertEqual(model["maxTokens"], 128000)
            self.assertTrue(model["reasoning"])
            self.assertTrue(model["compat"]["forceAdaptiveThinking"])
        self.assertEqual(cmd[1:5], ["-p", "--thinking", "off", "fix it"])
        self.assertEqual(settings["thinking"], {
            "level": "off",
            "argv_override": True,
            "model_reasoning": True,
        })
        self.assertEqual(settings["context_window"], 200000)
        self.assertTrue(settings["matched_config"])

    def test_opencode_config_sets_200k_and_disabled_thinking(self):
        smoke = _load_smoke("data/opencode-harness-smoke/cell.py", "oc_matched_on")
        with _Env(**{ENV: "1"}):
            pinned = smoke.comparison_config("http://127.0.0.1:9/v1")
            self.assertIsNone(opencode.comparison_variant("claude-opus-5-5"))
            self.assertEqual(opencode.comparison_variant("claude-opus-4-8"), "medium")
        model = pinned["provider"]["anthropic"]["models"]["claude-sonnet-5-5"]
        self.assertEqual(model["limit"], {"context": 200000, "output": 128000})
        self.assertEqual(model["options"]["thinking"], {"type": "between_tools"})
        self.assertNotIn("output_config", model["options"])
        self.assertEqual(pinned["model"], "anthropic/claude-sonnet-5-5")
        self.assertEqual(pinned["small_model"], "anthropic/claude-sonnet-5-5")
        # Provider options (the proxy key) stay put.
        self.assertEqual(
            pinned["provider"]["anthropic"]["options"],
            {"apiKey": "proxy", "baseURL": "http://127.0.0.1:9/v1"},
        )
        # The historical helper is unchanged when called on its own.
        plain = anthropic_proxy_config("http://127.0.0.1:9/v1", include_endpoint=True)
        self.assertEqual(
            plain["provider"]["anthropic"]["models"]["claude-opus-5-5"]["limit"]["context"],
            1000000,
        )
        shaped = apply_matched_pair_config(plain)
        opus = shaped["provider"]["anthropic"]["models"]["claude-opus-5-5"]
        self.assertEqual(opus["limit"]["context"], 200000)
        self.assertEqual(opus["options"]["thinking"], {"type": "adaptive"})
        self.assertEqual(opus["options"]["output_config"], {"effort": "low"})

    def test_explicit_context_window_beats_the_flag(self):
        early = _tree()
        self.addCleanup(lambda: __import__("shutil").rmtree(early, ignore_errors=True))
        with _Env(**{ENV: "1"}):
            pinned = json.loads(model_document(
                early, "http://127.0.0.1:9", "models.json", context_window=1000000,
            ))
            flagged = json.loads(model_document(early, "http://127.0.0.1:9", "models.json"))
        self.assertEqual(pinned["providers"]["vertex-anthropic"]["models"][0]["contextWindow"], 1000000)
        self.assertEqual(flagged["providers"]["vertex-anthropic"]["models"][0]["contextWindow"], 200000)

    def test_proxy_shapes_the_request_and_records_server_thinking_tokens(self):
        request = {
            "model": "claude-sonnet-5-5",
            "max_tokens": 16,
            "messages": [{"role": "user", "content": "hi"}],
        }
        usage = {
            "input_tokens": 4,
            "output_tokens": 9,
            "reasoning_tokens": 40,
            "output_tokens_details": {"thinking_tokens": 0, "reasoning_tokens": 40},
        }
        httpd, thread, upstream = _listen([usage])
        ledger = Path(self._tmpdir())
        proxy = start_proxy(
            "proj", token="tok", upstream=upstream, ledger_dir=ledger,
            thinking_mode="default", model="claude-sonnet-5-5",
        )
        self.addCleanup(proxy.close)
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        self.addCleanup(lambda: thread.join(timeout=2))
        with _Env(**{ENV: "1", "OBENCH_MATCHED_EFFORT": None}):
            status, _payload = _post(
                proxy.base_url + "/c/cell1/v1/messages",
                json.dumps(request).encode("utf-8"),
            )
        self.assertEqual(status, 200)
        forwarded = json.loads(httpd.seen[-1])
        self.assertEqual(forwarded["thinking"], {"type": "between_tools"})
        self.assertNotIn("output_config", forwarded)
        self.assertNotIn("model", forwarded)
        rows = [
            json.loads(line)
            for line in (ledger / "cell1.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(rows[0]["thinking_sent"], "between_tools")
        self.assertEqual(rows[0]["thinking_json"], '{"type":"between_tools"}')
        self.assertIsNone(rows[0]["output_config_json"])
        self.assertEqual(rows[0]["thinking_tokens"], 0)
        # The reasoning counter on the same usage object is a different field.
        self.assertEqual(rows[0]["usage"]["reasoning_tokens"], 40)
        observed = read_proxy_observed(ledger, "cell1")
        self.assertEqual(observed, [{
            "thinking_mode": "default",
            "thinking_sent": "between_tools",
            "thinking_json": '{"type":"between_tools"}',
            "output_config_json": None,
            "thinking_tokens": 0,
            "reasoning_tokens": 40,
        }])
        result = attach_thinking({"task": "demo"}, "off", rows)
        self.assertEqual(result["thinking_sent"], ["between_tools"])
        self.assertEqual(result["thinking_tokens"], [0])

    def test_proxy_records_a_nonzero_server_count_separately_from_reasoning(self):
        usage = {
            "input_tokens": 3,
            "output_tokens": 11,
            "output_tokens_details": {"thinking_tokens": 7},
            "reasoning_tokens": 1,
        }
        httpd, thread, upstream = _listen([usage])
        ledger = Path(self._tmpdir())
        proxy = start_proxy(
            "proj", token="tok", upstream=upstream, ledger_dir=ledger,
        )
        self.addCleanup(proxy.close)
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        self.addCleanup(lambda: thread.join(timeout=2))
        body = {
            "model": "claude-opus-5-5",
            "max_tokens": 8,
            "messages": [{"role": "user", "content": "think"}],
            "thinking": {"type": "adaptive"},
        }
        with _Env(**{ENV: "1", "OBENCH_MATCHED_EFFORT": None}):
            status, _payload = _post(
                proxy.base_url + "/c/cell2/v1/messages",
                json.dumps(body).encode("utf-8"),
            )
        self.assertEqual(status, 200)
        forwarded = json.loads(httpd.seen[-1])
        self.assertEqual(forwarded["thinking"], {"type": "adaptive"})
        self.assertEqual(forwarded["output_config"], {"effort": "low"})
        row = json.loads((ledger / "cell2.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(row["thinking_sent"], "adaptive+effort")
        self.assertEqual(row["thinking_json"], '{"type":"adaptive"}')
        self.assertEqual(row["output_config_json"], '{"effort":"low"}')
        self.assertEqual(row["thinking_tokens"], 7)
        self.assertEqual(row["usage"]["reasoning_tokens"], 1)

    def test_historical_request_is_forwarded_without_a_thinking_field(self):
        usage = {"input_tokens": 2, "output_tokens": 3, "reasoning_tokens": 8}
        httpd, thread, upstream = _listen([usage])
        ledger = Path(self._tmpdir())
        proxy = start_proxy(
            "proj", token="tok", upstream=upstream, ledger_dir=ledger,
        )
        self.addCleanup(proxy.close)
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        self.addCleanup(lambda: thread.join(timeout=2))
        body = {
            "model": "claude-opus-5-5",
            "max_tokens": 8,
            "messages": [{"role": "user", "content": "plain"}],
        }
        before = json.dumps(body)
        with _Env(**{ENV: None}):
            status, _payload = _post(
                proxy.base_url + "/c/plain/v1/messages",
                before.encode("utf-8"),
            )
        self.assertEqual(status, 200)
        forwarded = json.loads(httpd.seen[-1])
        self.assertNotIn("thinking", forwarded)
        self.assertEqual(json.dumps(body), before)
        row = json.loads((ledger / "plain.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(row["thinking_sent"], "none")
        self.assertIsNone(row["thinking_tokens"])
        self.assertIsNone(row["thinking_json"])
        self.assertIsNone(row["output_config_json"])

    def test_dry_run_plan_names_the_matched_profile_only_when_asked(self):
        prs = select_prs(parse_prs(FIXTURE), ["623"])
        out = Path(self._tmpdir())
        kwargs = dict(
            jobs=1, model="claude-opus-5-5", timeout_s=5, cache=out,
            max_cost_usd=None, dry_run=True, tasks_dir=out,
        )
        with _Env(**{ENV: None}):
            plain, launched, stopped = drive(prs, ("make-it-run",), 1, out, **kwargs)
            matched, launched_on, stopped_on = drive(
                prs, ("make-it-run",), 1, out, matched_config=True, **kwargs,
            )
            self.assertIsNone(os.environ.get(ENV))
        self.assertEqual(launched, 0)
        self.assertEqual(launched_on, 0)
        self.assertIsNone(stopped)
        self.assertIsNone(stopped_on)
        self.assertNotIn("matched-config", plain)
        self.assertIn(
            "matched-config: context=200000 sonnet=between_tools opus=adaptive effort=low",
            matched,
        )
        self.assertIn("623", plain)
        self.assertIn("cells: 2", plain)

    def _tmpdir(self):
        import tempfile
        path = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(path, ignore_errors=True))
        return path


class ThinkingFallbackTests(unittest.TestCase):
    def test_per_model_selection(self):
        with _Env(**{ENV: "1", "OBENCH_MATCHED_EFFORT": None}):
            sonnet_thinking, sonnet_config = matched_request_thinking("claude-sonnet-5-5")
            opus_thinking, opus_config = matched_request_thinking("anthropic/claude-opus-5-5@default")
            other_thinking, other_config = matched_request_thinking("claude-haiku-4-5")
            self.assertEqual(matched_opus_effort(), "low")
        self.assertEqual(sonnet_thinking, {"type": "between_tools"})
        self.assertIsNone(sonnet_config)
        self.assertEqual(opus_thinking, {"type": "adaptive"})
        self.assertEqual(opus_config, {"effort": "low"})
        self.assertEqual(other_thinking, {"type": "disabled"})
        self.assertIsNone(other_config)

        sonnet = {"model": "claude-sonnet-5-5", "max_tokens": 8, "messages": []}
        opus = {
            "model": "claude-opus-5-5", "max_tokens": 8, "messages": [],
            "thinking": {"type": "disabled"},
            "output_config": {"effort": "max", "extra": True},
        }
        other = {"model": "claude-haiku-4-5", "max_tokens": 8, "output_config": {"effort": "high"}}
        with _Env(**{ENV: "1", "OBENCH_MATCHED_EFFORT": None}):
            self.assertTrue(apply_disabled_thinking(sonnet, "claude-sonnet-5-5"))
            self.assertTrue(apply_disabled_thinking(opus, "claude-opus-5-5"))
            self.assertTrue(apply_disabled_thinking(other, "claude-haiku-4-5"))
        self.assertEqual(sonnet["thinking"], {"type": "between_tools"})
        self.assertNotIn("output_config", sonnet)
        self.assertEqual(opus["thinking"], {"type": "adaptive"})
        self.assertEqual(opus["output_config"], {"effort": "low"})
        self.assertEqual(other["thinking"], {"type": "disabled"})
        self.assertNotIn("output_config", other)
        self.assertEqual(classify_thinking(sonnet), "between_tools")
        self.assertEqual(classify_thinking(opus), "adaptive+effort")
        self.assertEqual(classify_thinking(other), "disabled")

    def test_effort_override_changes_only_the_opus_level(self):
        body = {"model": "claude-opus-5-5", "max_tokens": 8, "messages": []}
        with _Env(**{ENV: "1", "OBENCH_MATCHED_EFFORT": "xhigh"}):
            self.assertEqual(matched_opus_effort(), "xhigh")
            apply_disabled_thinking(body, "claude-opus-5-5")
            self.assertEqual(body["output_config"], {"effort": "xhigh"})
            self.assertEqual(
                canonical_object_json(body["output_config"]),
                '{"effort":"xhigh"}',
            )
        with _Env(**{ENV: "1", "OBENCH_MATCHED_EFFORT": "not a level"}):
            self.assertEqual(matched_opus_effort(), "low")
        with _Env(**{ENV: None, "OBENCH_MATCHED_EFFORT": "high"}):
            untouched = {"model": "claude-opus-5-5", "max_tokens": 8}
            before = json.dumps(untouched)
            self.assertFalse(apply_disabled_thinking(untouched, "claude-opus-5-5"))
            self.assertEqual(json.dumps(untouched), before)

    def test_ledger_stores_canonical_bytes_and_keeps_thinking_tokens(self):
        usage = {
            "input_tokens": 1,
            "output_tokens": 2,
            "output_tokens_details": {"thinking_tokens": 0},
            "reasoning_tokens": 9,
        }
        httpd, thread, upstream = _listen([usage, usage])
        ledger = Path(self._tmpdir())
        proxy = start_proxy(
            "proj", token="tok", upstream=upstream, ledger_dir=ledger,
            model="claude-opus-5-5", route_by_request=True,
        )
        self.addCleanup(proxy.close)
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        self.addCleanup(lambda: thread.join(timeout=2))
        bodies = [
            {"model": "claude-sonnet-5-5", "max_tokens": 8, "messages": [{"role": "user", "content": "s"}]},
            {"model": "claude-opus-5-5", "max_tokens": 8, "messages": [{"role": "user", "content": "o"}],
             "output_config": {"z": 1, "effort": "max"}},
        ]
        with _Env(**{ENV: "1", "OBENCH_MATCHED_EFFORT": "medium"}):
            for body in bodies:
                status, _payload = _post(
                    proxy.base_url + "/c/wire/v1/messages",
                    json.dumps(body).encode("utf-8"),
                )
                self.assertEqual(status, 200)
        rows = [
            json.loads(line)
            for line in (ledger / "wire.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(rows[0]["thinking_json"], '{"type":"between_tools"}')
        self.assertIsNone(rows[0]["output_config_json"])
        self.assertEqual(rows[0]["thinking_tokens"], 0)
        self.assertEqual(rows[0]["usage"]["reasoning_tokens"], 9)
        self.assertEqual(rows[1]["thinking_json"], '{"type":"adaptive"}')
        self.assertEqual(rows[1]["output_config_json"], '{"effort":"medium"}')
        self.assertEqual(rows[1]["thinking_sent"], "adaptive+effort")
        forwarded = [json.loads(raw) for raw in httpd.seen]
        self.assertEqual(forwarded[0]["thinking"], {"type": "between_tools"})
        self.assertNotIn("output_config", forwarded[0])
        self.assertEqual(forwarded[1]["output_config"], {"effort": "medium"})
        self.assertNotIn("z", forwarded[1]["output_config"])
        # Unsorted keys still canonicalize.
        self.assertEqual(
            canonical_object_json({"effort": "medium", "a": 1}),
            '{"a":1,"effort":"medium"}',
        )

    def test_identical_bytes_gate_passes_within_a_model_and_fails_on_drift(self):
        sonnet = {
            "record_type": "request",
            "upstream_model": "claude-sonnet-5-5",
            "thinking_json": '{"type":"between_tools"}',
            "output_config_json": None,
        }
        opus = {
            "record_type": "request",
            "upstream_model": "claude-opus-5-5",
            "thinking_json": '{"type":"adaptive"}',
            "output_config_json": '{"effort":"low"}',
        }
        self.assertTrue(wire_bytes_identical([
            sonnet, dict(sonnet), opus, dict(opus),
        ]))
        self.assertTrue(wire_bytes_identical([]))
        drifted = dict(opus)
        drifted["output_config_json"] = '{"effort":"high"}'
        self.assertFalse(wire_bytes_identical([opus, drifted]))
        other_thinking = dict(sonnet)
        other_thinking["thinking_json"] = '{"type":"disabled"}'
        self.assertFalse(wire_bytes_identical([sonnet, other_thinking]))

    def test_dry_run_plan_shows_the_effort_override(self):
        prs = select_prs(parse_prs(FIXTURE), ["623"])
        out = Path(self._tmpdir())
        with _Env(**{ENV: None, "OBENCH_MATCHED_EFFORT": None}):
            plan, _launched, _stopped = drive(
                prs, ("make-it-run",), 1, out,
                jobs=1, model="claude-opus-5-5", timeout_s=5, cache=out,
                max_cost_usd=None, dry_run=True, tasks_dir=out,
                matched_config=True, matched_effort="high",
            )
            self.assertIsNone(os.environ.get("OBENCH_MATCHED_EFFORT"))
        self.assertIn("opus=adaptive effort=high", plan)

    def _tmpdir(self):
        import tempfile
        path = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(path, ignore_errors=True))
        return path


def _tree() -> Path:
    import tempfile
    root = Path(tempfile.mkdtemp())
    src = root / "packages" / "coding-agent" / "src"
    src.mkdir(parents=True)
    (src / "models.ts").write_text("models.json\n", encoding="utf-8")
    return root
