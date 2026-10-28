"""Proxy-ledger cost, spend stop, metadata ADC, and the OpenCode zero bill."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from thesis.ab.run_ab import apply_cell_meter, main, over_budget
from thesis.ab.summarize import proxy_cost_from_records, proxy_cost_usd, row_cost
from thesis.ab.vertex_anthropic_proxy import AdcToken, ProxyError, adc_credentials_path


def _oc_cell():
    import importlib.util
    path = Path(__file__).resolve().parents[2] / "data" / "opencode-harness-smoke" / "cell.py"
    spec = importlib.util.spec_from_file_location("opencode_bridge_cell_cost", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Env:
    def __init__(self, **updates):
        self.updates = updates

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


_SMOKE = {
    "input_uncached": 12,
    "output": 3956,
    "cache_read": 0,
    "cache_write": 49813,
}


def _smoke_cost() -> float:
    return proxy_cost_usd("claude-sonnet-5-5", **_SMOKE)


class ProxyCostTests(unittest.TestCase):
    def test_ledger_tokens_price_at_vertex_list_rates(self):
        cost = _smoke_cost()
        self.assertAlmostEqual(cost, (12 * 2 + 3956 * 10 + 49813 * 2.5) / 1_000_000)
        self.assertGreater(cost, 0.1)
        records = [{
            "record_type": "request",
            "upstream_model": "claude-sonnet-5-5",
            **_SMOKE,
        }]
        self.assertAlmostEqual(proxy_cost_from_records(records), cost)

    def test_cell_record_keeps_proxy_cost_apart_from_harness_tokens(self):
        ledger = Path(tempfile.mkdtemp())
        cell_id = "cell1"
        (ledger / f"{cell_id}.jsonl").write_text(json.dumps({
            "record_type": "request",
            "upstream_model": "claude-sonnet-5-5",
            **_SMOKE,
        }) + "\n", encoding="utf-8")
        harness = row_cost({
            "upstream_model": "claude-sonnet-5-5",
            "tokens_input_uncached": 9_000_000,
            "tokens_output": 0,
            "tokens_cache_read": 0,
            "tokens_cache_write": 0,
        })
        row = {
            "tokens_input_uncached": 9_000_000,
            "tokens_output": 0,
            "tokens_cache_read": 0,
            "tokens_cache_write": 0,
        }
        apply_cell_meter(row, {"ledger_dir": str(ledger), "cell_id": cell_id})
        self.assertAlmostEqual(row["proxy_cost_usd"], _smoke_cost())
        self.assertLess(row["proxy_cost_usd"], harness)

    def test_max_spend_sums_proxy_cost_not_harness_tokens(self):
        out = Path(tempfile.mkdtemp())
        path = out / "1" / "cells" / "with" / "task" / "1.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({
            "failure_class": "solved",
            "upstream_model": "claude-sonnet-5-5",
            "tokens_input_uncached": 9_000_000,
            "tokens_output": 0,
            "tokens_cache_read": 0,
            "tokens_cache_write": 0,
            "proxy_cost_usd": 40.0,
        }), encoding="utf-8")
        self.assertIsNone(over_budget(out, 50))
        reason = over_budget(out, 40)
        self.assertIn("proxy cost", reason)
        self.assertIn("40.00", reason)

    def test_negative_max_spend_is_rejected(self):
        self.assertEqual(main(["/tmp/no-such-prs.csv", "--max-spend", "-1"]), 2)
        self.assertEqual(main([
            "/tmp/no-such-prs.csv", "--max-spend", "50", "--max-cost-usd", "10",
        ]), 2)


class OpenCodeZeroBillTests(unittest.TestCase):
    def test_requests_cost_uses_the_ledger_not_empty_proxy_fields(self):
        from obench.adapters.pi_harness import totals_path
        ledger = Path(tempfile.mkdtemp())
        cell_id = "362e87ae1e9a8384"
        payload = {"all": {**_SMOKE, "calls": 4}, "main": {**_SMOKE, "calls": 4}}
        Path(totals_path(str(ledger), cell_id)).write_text(
            json.dumps(payload) + "\n", encoding="utf-8",
        )
        cost = _oc_cell().requests_cost_usd("claude-sonnet-5-5", ledger, cell_id)
        self.assertAlmostEqual(cost, _smoke_cost())
        self.assertNotEqual(cost, 0.0)
        self.assertIsNone(_oc_cell().requests_cost_usd("claude-sonnet-5-5", ledger, "missing"))


class AdcSelectionTests(unittest.TestCase):
    def test_missing_file_uses_the_metadata_server(self):
        home = tempfile.mkdtemp()
        with _Env(HOME=home, OBENCH_ADC_METADATA=None, GOOGLE_APPLICATION_CREDENTIALS=None):
            self.assertIsNone(adc_credentials_path())
            token = AdcToken(now=lambda: 1000.0)
            self.assertTrue(token._use_metadata())
            with patch(
                "thesis.ab.vertex_anthropic_proxy._metadata_token",
                return_value=("meta-tok", 1300.0),
            ) as fetch:
                self.assertEqual(token._fetch(), ("meta-tok", 1300.0))
            fetch.assert_called_once()

    def test_existing_file_stays_on_file_adc(self):
        home = Path(tempfile.mkdtemp())
        path = home / ".config" / "gcloud" / "application_default_credentials.json"
        path.parent.mkdir(parents=True)
        path.write_text("{}\n", encoding="utf-8")
        with _Env(HOME=str(home), OBENCH_ADC_METADATA=None, GOOGLE_APPLICATION_CREDENTIALS=None):
            self.assertEqual(adc_credentials_path(), path)
            self.assertFalse(AdcToken()._use_metadata())

    def test_metadata_failure_names_the_missing_file(self):
        home = tempfile.mkdtemp()
        with _Env(HOME=home, OBENCH_ADC_METADATA=None, GOOGLE_APPLICATION_CREDENTIALS=None):
            token = AdcToken(now=lambda: 0.0)
            with patch(
                "thesis.ab.vertex_anthropic_proxy._metadata_token",
                side_effect=ProxyError("down"),
            ):
                with self.assertRaises(ProxyError) as caught:
                    token._fetch()
        message = str(caught.exception)
        self.assertIn("application_default_credentials.json", message)
        self.assertIn("metadata-server ADC failed", message)

    def test_flag_zero_fails_before_a_cell_when_the_file_is_missing(self):
        home = tempfile.mkdtemp()
        with _Env(HOME=home, OBENCH_ADC_METADATA="0", GOOGLE_APPLICATION_CREDENTIALS=None):
            token = AdcToken()
            self.assertFalse(token._use_metadata())
            with self.assertRaises(ProxyError) as caught:
                token._fetch()
        self.assertIn("OBENCH_ADC_METADATA=0", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
