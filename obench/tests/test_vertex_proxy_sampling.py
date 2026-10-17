import unittest

from thesis.ab.vertex_anthropic_proxy import strip_deprecated_sampling


class DeprecatedSamplingTests(unittest.TestCase):
    def test_sonnet_drops_temperature(self):
        body = {"temperature": 0.0, "top_p": 0.9, "max_tokens": 5}
        self.assertEqual(strip_deprecated_sampling(body, "claude-sonnet-5-5"), ["param:temperature", "param:top_p"])
        self.assertEqual(body, {"max_tokens": 5})

    def test_other_models_keep_temperature(self):
        body = {"temperature": 0.0}
        self.assertEqual(strip_deprecated_sampling(body, "claude-opus-5-5"), [])
        self.assertEqual(body, {"temperature": 0.0})
