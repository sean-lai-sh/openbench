import os
import unittest
from unittest import mock

from thesis.ab.vertex_anthropic_proxy import BLOCK_BINDING_ENV, apply_block_binding


def _body(with_thinking=True, thinking=None):
    content = [{"type": "text", "text": "hi"}]
    if with_thinking:
        content.insert(0, {"type": "thinking", "thinking": "x", "signature": "s"})
    body = {"messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": content}]}
    if thinking is not None:
        body["thinking"] = thinking
    return body


class BlockBindingTests(unittest.TestCase):
    def test_off_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(BLOCK_BINDING_ENV, None)
            body = _body()
            self.assertIsNone(apply_block_binding(body))
            self.assertNotIn("thinking", body)

    def test_drop_block_added_when_history_has_thinking(self):
        with mock.patch.dict(os.environ, {BLOCK_BINDING_ENV: "drop_block"}):
            body = _body()
            self.assertEqual(apply_block_binding(body), "drop_block")
            self.assertEqual(body["thinking"], {
                "type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "drop_block"}})
            kept = _body(thinking={"type": "adaptive", "x": 1})
            apply_block_binding(kept)
            self.assertEqual(kept["thinking"]["x"], 1)

    def test_no_thinking_in_history_is_untouched(self):
        with mock.patch.dict(os.environ, {BLOCK_BINDING_ENV: "drop_block"}):
            body = _body(with_thinking=False)
            self.assertIsNone(apply_block_binding(body))
            self.assertNotIn("thinking", body)
