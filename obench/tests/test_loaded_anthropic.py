"""loaded_anthropic: User-Agent capture, row aggregate, gate rule, and the
minified-bundle scanner fallback (fixtures modeled on the real 26821/50272
binaries)."""
import os
import tempfile
import unittest
from unittest import mock

from obench.adapters import opencode
from obench.provider_embedded import scan
from obench.provider_ua import aggregate, loaded_anthropic_from_ua
from obench.run import apply_proxy_ledger
from thesis.ab.step8_gate import judge

UA_3071 = "opencode/1.0 ai-sdk/anthropic/3.0.71 ai-sdk/provider-utils/4.0.1 runtime/bun/1.3.0"
# 26821 (3.0.71): lazy import() compiled in, minified version var before the template.
FIX_26821 = (b'\x00var aG="3.0.71",bQ=function(){};function cZ(e){return{"user-agent":'
             b'`ai-sdk/anthropic/${aG}`,...e}}\x00')
# 50272 (3.0.111): `var` list form, definition after an unrelated var of the same shape.
FIX_50272 = (b'\x00var Zt="1.0.0";var q1=1,UQ="3.0.111",W2=2;\nfunction hX(t){t=withUserAgentSuffix(t,'
             b'`ai-sdk/anthropic/${UQ}`)}\x00')


class UATest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(loaded_anthropic_from_ua(UA_3071), "3.0.71")
        self.assertEqual(loaded_anthropic_from_ua("ai-sdk/anthropic/2.0.0-beta.11"), "2.0.0-beta.11")
        self.assertEqual(loaded_anthropic_from_ua("Bun/1.3"), "")
        self.assertEqual(loaded_anthropic_from_ua(None), "")
        self.assertEqual(loaded_anthropic_from_ua("ai-sdk/anthropic/1 ai-sdk/anthropic/2"), "")

    def test_aggregate(self):
        self.assertEqual(aggregate([None, "3.0.71", "3.0.71"]), "3.0.71")
        self.assertEqual(aggregate([None, ""]), "")
        self.assertEqual(aggregate(["3.0.71", "2.0.58"]), "mixed:2.0.58,3.0.71")

    def test_row_from_ledger(self):
        recs = [{"status": 200, "loaded_anthropic": "3.0.111"}, {"status": 200, "loaded_anthropic": None}]
        self.assertEqual(apply_proxy_ledger({}, recs)["loaded_anthropic"], "3.0.111")
        self.assertIsNone(apply_proxy_ledger({}, [{"status": 200}])["loaded_anthropic"])


class GateTest(unittest.TestCase):
    def test_pass_needs_ua_equal_pin(self):
        self.assertTrue(judge({"loaded_anthropic": "3.0.71"}, "3.0.71")[0])
        ok, why = judge({"loaded_anthropic": "3.0.111"}, "3.0.71")
        self.assertFalse(ok)
        self.assertIn("3.0.111 != pin 3.0.71", why)

    def test_probe_alone_no_longer_passes(self):
        ok, why = judge({"probe_method": "strace", "provider_loaded_version": "3.0.71"}, "3.0.71")
        self.assertFalse(ok)
        self.assertIn("loaded_anthropic unproven", why)

    def test_probe_must_agree_when_present(self):
        cell = {"loaded_anthropic": "3.0.71", "probe_method": "strace", "provider_loaded_version": "3.0.64"}
        self.assertFalse(judge(cell, "3.0.71")[0])

    def test_mixed_never_passes(self):
        self.assertFalse(judge({"loaded_anthropic": "mixed:3.0.71,3.0.111"}, "3.0.71")[0])

    def test_missing_probe_fields_ok_other_missing_fail(self):
        cell = {"loaded_anthropic": "3.0.71", "missing_fields": ["probe_method", "provider_loaded_version"]}
        self.assertTrue(judge(cell, "3.0.71")[0])
        cell["missing_fields"].append("route")
        self.assertFalse(judge(cell, "3.0.71")[0])


class MinifiedScanTest(unittest.TestCase):
    def test_26821_shape(self):
        self.assertEqual(scan(FIX_26821), "3.0.71")

    def test_50272_shape(self):
        self.assertEqual(scan(FIX_50272), "3.0.111")

    def test_definition_after_template(self):
        self.assertEqual(scan(b'x=`ai-sdk/anthropic/${k9}`;var k9="2.0.58";'), "2.0.58")

    def test_unresolved_template(self):
        self.assertEqual(scan(b'x=`ai-sdk/anthropic/${k9}`;'), "")

    def test_other_provider_template_ignored(self):
        self.assertEqual(scan(b'var a="9.9.9";x=`ai-sdk/openai/${a}`'), "")


class PinRootTest(unittest.TestCase):
    def test_container_fallback(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"HOME": d}), \
                mock.patch.object(opencode, "CONTAINER_PIN_ROOT", d):
            os.environ.pop(opencode.PIN_ROOT_ENV, None)
            self.assertEqual(opencode._pin_root({}), d)

    def test_env_wins(self):
        with mock.patch.dict(os.environ, {opencode.PIN_ROOT_ENV: "/x/pins"}):
            self.assertEqual(opencode._pin_root({}), "/x/pins")


if __name__ == "__main__":
    unittest.main()
