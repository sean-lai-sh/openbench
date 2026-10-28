import json

from obench.adapters.pi_harness import models_document


def test_models_document_forces_adaptive_thinking():
    for model in ("claude-opus-5-5", "claude-sonnet-5-5"):
        doc = json.loads(models_document("http://127.0.0.1:1/c/x", model))
        (provider,) = doc["providers"].values()
        compat = provider["models"][0]["compat"]
        assert compat["forceAdaptiveThinking"] is True
        assert compat["supportsTemperature"] is False
