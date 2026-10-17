import unittest

from thesis.ab.vertex_anthropic_proxy import strip_deprecated_sampling


class DeprecatedSamplingTests(unittest.TestCase):
    def test_sonnet_drops_temperature(self):
        body = {"temperature": 0.0, "top_p": 0.9, "max_tokens": 5}
        self.assertEqual(strip_deprecated_sampling(body, "claude-sonnet-5-5"), ["param:temperature", "param:top_p"])
        self.assertEqual(body, {"max_tokens": 5})

    def test_opus_drops_temperature(self):
        # Vertex Opus 5.5 answers 400 "`temperature` is deprecated for this model".
        body = {"temperature": 0.0, "top_k": 5, "max_tokens": 5}
        self.assertEqual(strip_deprecated_sampling(body, "claude-opus-5-5@default"), ["param:temperature", "param:top_k"])
        self.assertEqual(body, {"max_tokens": 5})

    def test_other_models_keep_temperature(self):
        body = {"temperature": 0.0}
        self.assertEqual(strip_deprecated_sampling(body, "claude-haiku-4-5"), [])
        self.assertEqual(body, {"temperature": 0.0})
