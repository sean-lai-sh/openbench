"""Per-cell proxy/trace fields and the off-protocol batch halt.

Pi and OpenCode smoke cells and ``run_ab`` cells record how many model
calls the proxy saw, how many the harness traced, which model was asked
for, which model and Vertex location were actually used, and whether that
left the batch protocol (``--vertex-model``, location ``global``).
"""

import csv
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from thesis.ab.compat import Assessment
from thesis.ab.durable import publish_text
from thesis.ab.prs import parse_prs
from thesis.ab.run_ab import (
    PROTOCOL_LOCATION,
    apply_cell_meter,
    attach_proxy_trace,
    batch_exit_code,
    cell_file,
    drive,
    main,
    off_protocol_halt,
    read_cell,
)
from thesis.ab.vertex_anthropic_proxy import LOCATION, _append_ledger

SHA_A = "a" * 40
SHA_B = "b" * 40


def _prs(directory: Path):
    path = directory / "prs.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "PR", "Title", "Category", "Harness change",
            "Merge commit SHA", "Parent/base SHA",
        ])
        writer.writeheader()
        writer.writerow({
            "PR": "1",
            "Title": "Title one",
            "Category": "tool",
            "Harness change": "Changes the bash timeout hint.",
            "Merge commit SHA": SHA_B,
            "Parent/base SHA": SHA_A,
        })
    return parse_prs(path)


def _drive(out: Path, prs, worker, *, trials: int = 1, vertex_model: str = "claude-sonnet-5-5",
           require_model_match: bool = False):
    def build_fn(sha, cache, repo=""):
        return Path("/tmp") / sha

    def assess_fn(binary):
        return Assessment("native", "listed", {}, False)

    return drive(
        prs, ("make-it-run",), trials, out,
        jobs=1, model="claude-opus-5-5", timeout_s=5, cache=out,
        max_cost_usd=None, dry_run=False, tasks_dir=Path("/tmp"),
        build_fn=build_fn, assess_fn=assess_fn, worker=worker,
        vertex_model=vertex_model,
        require_model_match=require_model_match,
    )


class ProxyTraceFieldTests(unittest.TestCase):
    def test_each_field_on_a_uniform_sonnet_cell(self):
        row = {"turns": 2}
        records = [
            {
                "requested_model": "claude-sonnet-5-5",
                "upstream_model": "claude-sonnet-5-5",
                "endpoint_location": "global",
            },
            {
                "requested_model": "claude-sonnet-5-5",
                "upstream_model": "claude-sonnet-5-5",
                "endpoint_location": "global",
            },
        ]
        attach_proxy_trace(row, records, "claude-sonnet-5-5", protocol_location="global")
        self.assertEqual(row["proxy_requests"], 2)
        self.assertEqual(row["trace_requests"], 2)
        self.assertEqual(row["untraced_requests"], 0)
        self.assertEqual(row["requested_model"], "claude-sonnet-5-5")
        self.assertFalse(row["requested_model_mixed"])
        self.assertEqual(row["upstream_model"], "claude-sonnet-5-5")
        self.assertFalse(row["upstream_model_mixed"])
        self.assertEqual(row["endpoint_location"], "global")
        self.assertFalse(row["endpoint_location_mixed"])
        self.assertEqual(row["protocol_model"], "claude-sonnet-5-5")
        self.assertFalse(row["off_protocol"])
        self.assertEqual(PROTOCOL_LOCATION, LOCATION)
        self.assertEqual(PROTOCOL_LOCATION, "global")

    def test_untraced_request_is_proxy_minus_harness_trace(self):
        # OpenCode gate cell: 4 ledger requests, 3 step_finish events.
        row = {"turns": 3}
        records = [
            {"requested_model": "claude-opus-5-5", "upstream_model": "claude-sonnet-5-5", "endpoint_location": "global"},
            {"requested_model": "claude-opus-5-5", "upstream_model": "claude-sonnet-5-5", "endpoint_location": "global"},
            {"requested_model": "claude-opus-5-5", "upstream_model": "claude-sonnet-5-5", "endpoint_location": "global"},
            {"requested_model": "claude-opus-5-5", "upstream_model": "claude-sonnet-5-5", "endpoint_location": "global"},
        ]
        attach_proxy_trace(row, records, "claude-sonnet-5-5")
        self.assertEqual(row["proxy_requests"], 4)
        self.assertEqual(row["trace_requests"], 3)
        self.assertEqual(row["untraced_requests"], 1)
        self.assertEqual(row["requested_model"], "claude-opus-5-5")
        self.assertEqual(row["upstream_model"], "claude-sonnet-5-5")
        self.assertFalse(row["off_protocol"])

    def test_trace_falls_back_to_usage_raw_and_stays_empty_without_either(self):
        row = {"usage_raw": [{}, {}, {}]}
        attach_proxy_trace(row, [], "claude-sonnet-5-5", ledger_present=True)
        self.assertEqual(row["proxy_requests"], 0)
        self.assertEqual(row["trace_requests"], 3)
        self.assertEqual(row["untraced_requests"], -3)
        self.assertFalse(row["off_protocol"])
        blank = {}
        attach_proxy_trace(blank, None, "claude-sonnet-5-5", ledger_present=False)
        self.assertIsNone(blank["proxy_requests"])
        self.assertIsNone(blank["trace_requests"])
        self.assertIsNone(blank["untraced_requests"])
        self.assertIsNone(blank["endpoint_location"])
        self.assertFalse(blank["off_protocol"])

    def test_mixed_models_and_locations_are_recorded_and_flagged(self):
        row = {"turns": 2}
        attach_proxy_trace(row, [
            {"requested_model": "claude-opus-5-5", "upstream_model": "claude-sonnet-5-5", "endpoint_location": "global"},
            {"requested_model": "claude-sonnet-5-5", "upstream_model": "claude-opus-5-5", "endpoint_location": "europe-west4"},
        ], "claude-sonnet-5-5")
        self.assertEqual(row["requested_model"], "claude-opus-5-5+claude-sonnet-5-5")
        self.assertTrue(row["requested_model_mixed"])
        self.assertEqual(row["upstream_model"], "claude-opus-5-5+claude-sonnet-5-5")
        self.assertTrue(row["upstream_model_mixed"])
        self.assertEqual(row["endpoint_location"], "europe-west4+global")
        self.assertTrue(row["endpoint_location_mixed"])
        self.assertTrue(row["off_protocol"])

    def test_wrong_upstream_model_is_off_protocol(self):
        row = {"turns": 1}
        attach_proxy_trace(row, [{
            "requested_model": "claude-opus-5-5",
            "upstream_model": "claude-opus-5-5",
            "endpoint_location": "global",
        }], "claude-sonnet-5-5")
        self.assertTrue(row["off_protocol"])
        self.assertEqual(row["endpoint_location"], "global")

    def test_non_global_location_is_off_protocol_when_the_model_matches(self):
        row = {"turns": 1}
        attach_proxy_trace(row, [{
            "requested_model": "claude-sonnet-5-5",
            "upstream_model": "claude-sonnet-5-5",
            "endpoint_location": "us-east5",
        }], "claude-sonnet-5-5", protocol_location="global")
        self.assertEqual(row["endpoint_location"], "us-east5")
        self.assertFalse(row["endpoint_location_mixed"])
        self.assertTrue(row["off_protocol"])

    def test_missing_endpoint_location_is_off_protocol(self):
        row = {"turns": 1}
        attach_proxy_trace(row, [{
            "requested_model": "claude-sonnet-5-5",
            "upstream_model": "claude-sonnet-5-5",
        }], "claude-sonnet-5-5")
        self.assertIsNone(row["endpoint_location"])
        self.assertTrue(row["off_protocol"])

    def test_ledger_row_stores_requested_model_and_endpoint_location(self):
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(directory, ignore_errors=True))
        _append_ledger(
            directory, "cell",
            {"input_tokens": 1, "output_tokens": 1},
            status=200,
            upstream_model="claude-sonnet-5-5",
            requested_model="claude-opus-5-5",
            endpoint_location="global",
        )
        row = json.loads((directory / "cell.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(row["requested_model"], "claude-opus-5-5")
        self.assertEqual(row["upstream_model"], "claude-sonnet-5-5")
        self.assertEqual(row["endpoint_location"], "global")


class OffProtocolHaltTests(unittest.TestCase):
    def test_matching_cell_does_not_halt(self):
        out = Path(tempfile.mkdtemp())
        calls = []

        def worker(spec):
            calls.append((spec["protocol_model"], spec["protocol_location"]))
            row = {"turns": 1}
            attach_proxy_trace(row, [{
                "requested_model": "claude-opus-5-5",
                "upstream_model": spec["protocol_model"],
                "endpoint_location": spec["protocol_location"],
            }], spec["protocol_model"], protocol_location=spec["protocol_location"])
            self.assertFalse(row["off_protocol"])
            self.assertEqual(row["endpoint_location"], "global")
            publish_text(Path(spec["cell_path"]), json.dumps(row))

        _plan, launched, stopped = _drive(out, _prs(out), worker)
        self.assertEqual(calls, [("claude-sonnet-5-5", "global"), ("claude-sonnet-5-5", "global")])
        self.assertEqual(launched, 2)
        self.assertIsNone(stopped)
        self.assertEqual(batch_exit_code(stopped), 0)

    def test_wrong_upstream_model_halts_the_batch(self):
        out = Path(tempfile.mkdtemp())
        calls = []

        def worker(spec):
            calls.append(spec["trial"])
            row = {"turns": 1}
            attach_proxy_trace(row, [{
                "upstream_model": "claude-opus-5-5",
                "requested_model": "claude-opus-5-5",
                "endpoint_location": "global",
            }], spec["protocol_model"], protocol_location=spec["protocol_location"])
            self.assertTrue(row["off_protocol"])
            publish_text(Path(spec["cell_path"]), json.dumps(row))

        _plan, launched, stopped = _drive(out, _prs(out), worker, trials=2)
        self.assertEqual(calls, [1])
        self.assertEqual(launched, 1)
        self.assertTrue(str(stopped).startswith("off-protocol halt"))
        self.assertIn("upstream_model=claude-opus-5-5", stopped)
        self.assertEqual(batch_exit_code(stopped), 1)

    def test_non_global_endpoint_location_halts_the_batch(self):
        out = Path(tempfile.mkdtemp())
        calls = []

        def worker(spec):
            calls.append(spec["side"])
            row = {"turns": 1}
            attach_proxy_trace(row, [{
                "upstream_model": spec["protocol_model"],
                "requested_model": spec["protocol_model"],
                "endpoint_location": "europe-west4",
            }], spec["protocol_model"], protocol_location=spec["protocol_location"])
            self.assertTrue(row["off_protocol"])
            self.assertEqual(row["endpoint_location"], "europe-west4")
            publish_text(Path(spec["cell_path"]), json.dumps(row))

        _plan, launched, stopped = _drive(out, _prs(out), worker)
        self.assertEqual(calls, ["without"])
        self.assertEqual(launched, 1)
        self.assertIn("endpoint_location=europe-west4", stopped)
        self.assertEqual(batch_exit_code(stopped), 1)
        saved = read_cell(cell_file(out, "1", "without", "make-it-run", 1))
        self.assertEqual(saved["endpoint_location"], "europe-west4")
        self.assertTrue(saved["off_protocol"])

    def test_resume_does_not_launch_after_an_off_protocol_cell(self):
        out = Path(tempfile.mkdtemp())
        existing = cell_file(out, "1", "without", "make-it-run", 1)
        publish_text(existing, json.dumps({
            "off_protocol": True,
            "upstream_model": "claude-sonnet-5-5",
            "protocol_model": "claude-sonnet-5-5",
            "endpoint_location": "us-east5",
        }))
        calls = []

        def worker(spec):
            calls.append(spec["side"])
            publish_text(Path(spec["cell_path"]), json.dumps({"off_protocol": False}))

        reason = off_protocol_halt(out)
        self.assertIn("endpoint_location=us-east5", reason)
        _plan, launched, stopped = _drive(out, _prs(out), worker)
        self.assertEqual(calls, [])
        self.assertEqual(launched, 0)
        self.assertEqual(stopped, reason)
        self.assertEqual(batch_exit_code(stopped), 1)


class RequireModelMatchTests(unittest.TestCase):
    def test_opus_served_as_sonnet_is_on_protocol_until_the_flag_is_set(self):
        records = [{
            "requested_model": "claude-opus-5-5",
            "upstream_model": "claude-sonnet-5-5",
            "endpoint_location": "global",
        }]
        plain = {"turns": 1}
        attach_proxy_trace(plain, records, "claude-sonnet-5-5")
        self.assertFalse(plain["off_protocol"])
        self.assertFalse(plain["require_model_match"])
        strict = {"turns": 1}
        attach_proxy_trace(strict, records, "claude-sonnet-5-5", require_model_match=True)
        self.assertTrue(strict["off_protocol"])
        self.assertTrue(strict["require_model_match"])
        self.assertEqual(strict["model_match_reason"], "model_mismatch")
        self.assertIsNone(plain["model_match_reason"])

    def test_provider_prefix_still_matches_the_upstream_id(self):
        row = {"turns": 1}
        attach_proxy_trace(row, [{
            "requested_model": "anthropic/claude-sonnet-5-5",
            "upstream_model": "claude-sonnet-5-5",
            "endpoint_location": "global",
        }], "claude-sonnet-5-5", require_model_match=True)
        self.assertFalse(row["off_protocol"])
        self.assertIsNone(row["model_match_reason"])
        self.assertEqual(row["requested_model"], "anthropic/claude-sonnet-5-5")
        self.assertEqual(row["upstream_model"], "claude-sonnet-5-5")

    def test_both_reasons_stay_distinct_on_one_cell(self):
        row = {"turns": 2}
        attach_proxy_trace(row, [
            {
                "requested_model": "claude-opus-5-5",
                "upstream_model": "claude-sonnet-5-5",
                "endpoint_location": "global",
            },
            {
                "upstream_model": "claude-sonnet-5-5",
                "endpoint_location": "global",
            },
        ], "claude-sonnet-5-5", require_model_match=True)
        self.assertEqual(row["model_match_reason"], "model_mismatch+model_unrecorded")
        self.assertTrue(row["off_protocol"])

    def test_missing_requested_model_is_unrecorded_not_a_mismatch(self):
        row = {"turns": 1}
        attach_proxy_trace(row, [{
            "upstream_model": "claude-sonnet-5-5",
            "endpoint_location": "global",
        }], "claude-sonnet-5-5", require_model_match=True)
        self.assertTrue(row["off_protocol"])
        self.assertEqual(row["model_match_reason"], "model_unrecorded")
        bare = {"turns": 1}
        attach_proxy_trace(bare, [{
            "requested_model": "claude-sonnet-5-5",
            "endpoint_location": "global",
        }], "claude-sonnet-5-5", require_model_match=True)
        self.assertEqual(bare["model_match_reason"], "model_unrecorded")
        self.assertNotIn("model_mismatch", bare["model_match_reason"])

    def test_flag_halts_the_batch_and_stays_off_by_default(self):
        def run(enabled: bool):
            out = Path(tempfile.mkdtemp())
            calls = []

            def worker(spec):
                calls.append(spec["require_model_match"])
                row = {"turns": 1}
                attach_proxy_trace(row, [{
                    "requested_model": "claude-opus-5-5",
                    "upstream_model": spec["protocol_model"],
                    "endpoint_location": spec["protocol_location"],
                }], spec["protocol_model"], protocol_location=spec["protocol_location"],
                   require_model_match=spec["require_model_match"])
                publish_text(Path(spec["cell_path"]), json.dumps(row))

            _plan, launched, stopped = _drive(
                out, _prs(out), worker, require_model_match=enabled,
            )
            return calls, launched, stopped

        calls, launched, stopped = run(False)
        self.assertEqual(calls, [False, False])
        self.assertEqual(launched, 2)
        self.assertIsNone(stopped)
        calls, launched, stopped = run(True)
        self.assertEqual(calls, [True])
        self.assertEqual(launched, 1)
        self.assertIn("requested_model=claude-opus-5-5", stopped)
        self.assertEqual(batch_exit_code(stopped), 1)

    def test_cli_defaults_the_flag_off(self):
        from unittest.mock import patch

        from thesis.ab.run_ab import main

        seen = []

        def fake_drive(*_args, **kwargs):
            seen.append(kwargs.get("require_model_match"))
            return "plan\n", 0, None

        argv = [
            "thesis/ab/fixtures/opencode-harness-prs.csv", "--pr", "623",
            "--task-map", "thesis/ab/fixtures/trigger-tasks.csv", "--dry-run",
        ]
        with patch("thesis.ab.run_ab.drive", fake_drive):
            self.assertEqual(main(argv), 0)
            self.assertEqual(main(argv + ["--require-model-match"]), 0)
        self.assertEqual(seen, [False, True])

    def test_comparison_smoke_launches_opencode_as_sonnet_and_requires_a_match(self):
        import importlib.util

        from thesis.ab.compat import PROXY_MODEL_ID, anthropic_proxy_config

        root = Path(__file__).resolve().parents[2]

        def load(relative, name):
            path = root / relative
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module

        opencode = load("data/opencode-harness-smoke/cell.py", "oc_model_match_smoke")
        pi = load("data/pi-harness-smoke/cell.py", "pi_model_match_smoke")
        self.assertEqual(opencode.MODEL_REF, "anthropic/claude-sonnet-5-5")
        self.assertEqual(opencode.MODEL_ID, "claude-sonnet-5-5")
        self.assertEqual(opencode.ADAPTER_MODEL, "claude-opus-5-5")
        oc_args = opencode.argument_parser().parse_args(["--out", "out", "--sha", "a" * 40])
        self.assertTrue(oc_args.require_model_match)
        self.assertEqual(oc_args.vertex_model, "claude-sonnet-5-5")
        opted_out = opencode.argument_parser().parse_args([
            "--out", "out", "--sha", "a" * 40, "--no-require-model-match",
        ])
        self.assertFalse(opted_out.require_model_match)
        pi_args = pi.argument_parser().parse_args(["--out", "out"])
        self.assertTrue(pi_args.require_model_match)
        pi_off = pi.argument_parser().parse_args(["--out", "out", "--no-require-model-match"])
        self.assertFalse(pi_off.require_model_match)
        default = anthropic_proxy_config("http://127.0.0.1:9/v1", include_endpoint=True)
        self.assertIn(PROXY_MODEL_ID, default["provider"]["anthropic"]["models"])
        sonnet = anthropic_proxy_config(
            "http://127.0.0.1:9/v1", include_endpoint=True,
            model_id=opencode.MODEL_ID, model_name="Claude Sonnet 5.5",
        )
        models = sonnet["provider"]["anthropic"]["models"]
        self.assertEqual(set(models), {"claude-sonnet-5-5"})
        self.assertEqual(models["claude-sonnet-5-5"]["name"], "Claude Sonnet 5.5")
        pinned = opencode.comparison_config("http://127.0.0.1:9/v1")
        self.assertEqual(pinned["model"], "anthropic/claude-sonnet-5-5")
        self.assertEqual(pinned["small_model"], "anthropic/claude-sonnet-5-5")
        self.assertNotIn("title", pinned)
        from obench.adapters.opencode import _config_body
        keys = (
            "OBENCH_OPENCODE_CONFIG_JSON",
            "OBENCH_OPENCODE_PERMISSION_CONFIG",
            "OBENCH_OPENCODE_PERMISSIONS",
            "OBENCH_OPENCODE_LSP",
            "OBENCH_OPENCODE_DISABLE_TOOLS",
        )
        saved = {key: os.environ.get(key) for key in keys}
        os.environ["OBENCH_OPENCODE_CONFIG_JSON"] = json.dumps(pinned)
        for key in keys[1:]:
            os.environ.pop(key, None)
        try:
            written = _config_body(False)
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        self.assertEqual(written["model"], "anthropic/claude-sonnet-5-5")
        self.assertEqual(written["small_model"], "anthropic/claude-sonnet-5-5")


def _ledger_row(*, requested, upstream="claude-sonnet-5-5"):
    row = {
        "record_type": "request",
        "upstream_model": upstream,
        "endpoint_location": "global",
        "status": 200,
    }
    if requested is not None:
        row["requested_model"] = requested
    return row


def _write_ledger(directory: Path, cell_id: str, requested, upstream="claude-sonnet-5-5") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    line = json.dumps(_ledger_row(requested=requested, upstream=upstream), sort_keys=True)
    (directory / f"{cell_id}.jsonl").write_text(line + "\n", encoding="utf-8")


class _FakeProxy:
    def __init__(self):
        self.base_url = "http://127.0.0.1:9"
        self.closed = False

    def close(self):
        self.closed = True

    def reached(self, _cell):
        return True


def _load_smoke(relative, name):
    import importlib.util
    path = Path(__file__).resolve().parents[2] / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HaltFiresFromLedgerTests(unittest.TestCase):
    """The halt has to come from a ledger row, then stop the runner."""

    def _run_ab(self, out: Path, *, flag: bool, requested):
        calls = []

        def worker(spec):
            calls.append((spec["side"], spec["trial"]))
            ledger = Path(tempfile.mkdtemp())
            _write_ledger(ledger, "cell-1", requested)
            row = {"turns": 1, "task": spec["task"], "trial": spec["trial"]}
            apply_cell_meter(
                row,
                {"ledger_dir": str(ledger), "cell_id": "cell-1"},
                protocol_model=spec["protocol_model"],
                protocol_location=spec["protocol_location"],
                require_model_match=spec["require_model_match"],
            )
            publish_text(Path(spec["cell_path"]), json.dumps(row))

        def build_fn(sha, cache, repo=""):
            return Path("/tmp") / sha

        def assess_fn(_binary):
            return Assessment("native", "listed", {}, False)

        real_drive = drive

        def wrapped(prs, tasks, trials, out_dir, **kwargs):
            kwargs["build_fn"] = build_fn
            kwargs["assess_fn"] = assess_fn
            kwargs["worker"] = worker
            kwargs["max_cost_usd"] = None
            return real_drive(prs, tasks, trials, out_dir, **kwargs)

        argv = [
            str(out / "prs.csv"), "--pr", "1", "--tasks", "make-it-run",
            "--trials", "2", "--jobs", "1",
            "--vertex-model", "claude-sonnet-5-5",
            "--out", str(out), "--cache", str(out),
        ]
        if flag:
            argv.append("--require-model-match")
        _prs(out)
        with patch("thesis.ab.run_ab.drive", wrapped):
            code = main(argv)
        return code, calls, read_cell(cell_file(out, "1", "without", "make-it-run", 1))

    def test_require_model_match_reads_the_ledger_and_exits_1(self):
        out = Path(tempfile.mkdtemp())
        code, calls, row = self._run_ab(out, flag=True, requested="claude-opus-5-5")
        self.assertEqual(code, 1)
        self.assertEqual(calls, [("without", 1)])
        self.assertTrue(row["off_protocol"])
        self.assertTrue(row["require_model_match"])
        self.assertEqual(row["model_match_reason"], "model_mismatch")
        self.assertEqual(row["requested_model"], "claude-opus-5-5")
        self.assertEqual(row["upstream_model"], "claude-sonnet-5-5")
        self.assertFalse(cell_file(out, "1", "without", "make-it-run", 2).is_file())

    def test_without_the_flag_an_opus_request_served_as_sonnet_keeps_going(self):
        out = Path(tempfile.mkdtemp())
        code, calls, row = self._run_ab(out, flag=False, requested="claude-opus-5-5")
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 4)
        self.assertFalse(row["off_protocol"])
        self.assertFalse(row["require_model_match"])

    def test_missing_requested_model_halts_only_when_the_flag_is_on(self):
        # Older ledgers have upstream_model and no requested_model. That is not
        # a match. The flag-on runner stops; the flag-off runner records null
        # and continues.
        out = Path(tempfile.mkdtemp())
        code, calls, row = self._run_ab(out, flag=True, requested=None)
        self.assertEqual(code, 1)
        self.assertEqual(calls, [("without", 1)])
        self.assertIsNone(row["requested_model"])
        self.assertEqual(row["upstream_model"], "claude-sonnet-5-5")
        self.assertEqual(row["model_match_reason"], "model_unrecorded")
        self.assertNotIn("model_mismatch", row["model_match_reason"])
        self.assertTrue(row["off_protocol"])

        out = Path(tempfile.mkdtemp())
        code, calls, row = self._run_ab(out, flag=False, requested=None)
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 4)
        self.assertIsNone(row["requested_model"])
        self.assertIsNone(row["model_match_reason"])
        self.assertFalse(row["off_protocol"])

    def test_opencode_smoke_halts_on_a_ledger_mismatch(self):
        module = _load_smoke("data/opencode-harness-smoke/cell.py", "oc_halt_fire")
        out = Path(tempfile.mkdtemp())
        binary = out / "opencode"
        binary.write_text("#!/bin/sh\n", encoding="utf-8")
        launched = []

        def fake_run(*_args, **_kwargs):
            launched.append(1)
            proxy = json.loads(os.environ["OBENCH_OPENCODE_PROXY"])
            cell_id = re.search(r"/c/([^/]+)", proxy["base_url"]).group(1)
            self.assertEqual(proxy["model_ref"], "anthropic/claude-sonnet-5-5")
            config = json.loads(os.environ["OBENCH_OPENCODE_CONFIG_JSON"])
            self.assertEqual(config["model"], "anthropic/claude-sonnet-5-5")
            self.assertEqual(config["small_model"], "anthropic/claude-sonnet-5-5")
            _write_ledger(out / "proxy-ledger", cell_id, "claude-opus-5-5")
            return {"turns": 1, "completed": True, "checker_exit": 0}

        with patch("thesis.ab.vertex_anthropic_proxy.start_from_env", return_value=_FakeProxy()), \
             patch("obench.run.run_cell", fake_run):
            code = module.main([
                "--out", str(out), "--binary", str(binary), "--exec", "local",
                "--require-model-match", "--vertex-model", "claude-sonnet-5-5",
            ])
        self.assertEqual(code, 1)
        self.assertEqual(launched, [1])
        saved = json.loads((out / "claude-sonnet-5-5.json").read_text(encoding="utf-8"))
        self.assertTrue(saved["off_protocol"])
        self.assertEqual(saved["requested_model"], "claude-opus-5-5")
        self.assertEqual(saved["upstream_model"], "claude-sonnet-5-5")
        self.assertEqual(saved["harness_model"], "anthropic/claude-sonnet-5-5")
        self.assertIn("requested_model=claude-opus-5-5", (out / "smoke.log").read_text(encoding="utf-8"))

    def test_pi_smoke_halts_before_the_next_model(self):
        module = _load_smoke("data/pi-harness-smoke/cell.py", "pi_halt_fire")
        out = Path(tempfile.mkdtemp())
        launched = []

        def fake_run(*args, **_kwargs):
            launched.append(args[2])
            cell_id = os.environ["OBENCH_VERTEX_CELL_ID"]
            _write_ledger(
                out / "proxy-ledger", cell_id, "claude-opus-5-5",
                upstream="claude-sonnet-5-5",
            )
            return {"turns": 1, "completed": True, "checker_exit": 0, "tokens": 1}

        with patch("thesis.ab.build_pi.binary", return_value=str(out / "pi")), \
             patch("thesis.ab.vertex_anthropic_proxy.start_from_env", return_value=_FakeProxy()), \
             patch("obench.run.run_cell", fake_run):
            code = module.main([
                "--out", str(out), "--cache", str(out), "--exec", "local",
                "--models", "claude-sonnet-5-5,claude-opus-5-5",
                "--require-model-match",
            ])
        self.assertEqual(code, 1)
        self.assertEqual(launched, ["claude-sonnet-5-5"])
        saved = json.loads((out / "claude-sonnet-5-5.json").read_text(encoding="utf-8"))
        self.assertTrue(saved["off_protocol"])
        self.assertFalse((out / "claude-opus-5-5.json").is_file())

    def test_smoke_missing_requested_model_does_not_count_as_a_match(self):
        module = _load_smoke("data/opencode-harness-smoke/cell.py", "oc_missing_request")
        out = Path(tempfile.mkdtemp())
        binary = out / "opencode"
        binary.write_text("#!/bin/sh\n", encoding="utf-8")

        def fake_run(*_args, **_kwargs):
            proxy = json.loads(os.environ["OBENCH_OPENCODE_PROXY"])
            cell_id = re.search(r"/c/([^/]+)", proxy["base_url"]).group(1)
            _write_ledger(out / "proxy-ledger", cell_id, None)
            return {"turns": 1, "completed": True, "checker_exit": 0}

        with patch("thesis.ab.vertex_anthropic_proxy.start_from_env", return_value=_FakeProxy()), \
             patch("obench.run.run_cell", fake_run):
            code = module.main([
                "--out", str(out), "--binary", str(binary), "--exec", "local",
            ])
        self.assertEqual(code, 1)
        saved = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        cell = saved["cells"][0]
        self.assertIsNone(cell["requested_model"])
        self.assertEqual(cell["upstream_model"], "claude-sonnet-5-5")
        self.assertEqual(cell["model_match_reason"], "model_unrecorded")
        self.assertTrue(cell["off_protocol"])
        log = (out / "smoke.log").read_text(encoding="utf-8")
        self.assertIn("requested_model=None", log)
        self.assertIn("model_match_reason=model_unrecorded", log)


if __name__ == "__main__":
    unittest.main()
