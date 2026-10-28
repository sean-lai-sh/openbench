"""OpenCode ledger cost and ADC selection for a bridge cell."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from obench.adapters.pi_harness import totals_path
from thesis.ab.summarize import row_cost
from thesis.ab.vertex_anthropic_proxy import AdcToken, ProxyError, adc_credentials_path


def _cell():
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
    "cache_read": 0,
    "cache_write": 49813,
    "calls": 4,
    "input_uncached": 12,
    "output": 3956,
}


class OpenCodeLedgerCostTests(unittest.TestCase):
    def test_smoke_ledger_is_priced_from_the_totals_file(self):
        ledger = Path(tempfile.mkdtemp())
        cell_id = "362e87ae1e9a8384"
        path = Path(totals_path(str(ledger), cell_id))
        path.write_text(json.dumps({"all": _SMOKE, "main": _SMOKE}) + "\n", encoding="utf-8")
        cost = _cell().requests_cost_usd("claude-sonnet-5-5", ledger, cell_id)
        priced = row_cost({
            "upstream_model": "claude-sonnet-5-5",
            "tokens_input_uncached": _SMOKE["input_uncached"],
            "tokens_output": _SMOKE["output"],
            "tokens_cache_read": _SMOKE["cache_read"],
            "tokens_cache_write": _SMOKE["cache_write"],
        })
        self.assertAlmostEqual(cost, priced)
        self.assertGreater(cost, 0.1)
        # The smoke bug: None tokens_proxy_* coerced with `or 0` bills nothing.
        zero = row_cost({
            "upstream_model": "claude-sonnet-5-5",
            "tokens_input_uncached": 0,
            "tokens_output": 0,
            "tokens_cache_read": 0,
            "tokens_cache_write": 0,
        })
        self.assertEqual(zero, 0.0)
        self.assertNotEqual(cost, zero)

    def test_missing_totals_is_not_a_zero_bill(self):
        ledger = Path(tempfile.mkdtemp())
        self.assertIsNone(_cell().requests_cost_usd("claude-sonnet-5-5", ledger, "absent"))


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
            token = AdcToken()
            self.assertFalse(token._use_metadata())

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
        self.assertIn("missing", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
