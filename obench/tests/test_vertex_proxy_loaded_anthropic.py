"""``loaded_anthropic`` from the caller's User-Agent on the Vertex proxy path."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from obench.tests.test_vertex_proxy_harness_api import MESSAGE, STREAM, _Vertex, _post
from thesis.ab.run_ab import apply_cell_meter
from thesis.ab.vertex_anthropic_proxy import (
    LOCATION, MODEL_ID, cell_ledger_path, cell_proxy_base, start_proxy,
)

BODY = {"model": MODEL_ID, "max_tokens": 16, "messages": [{"role": "user", "content": "hi"}]}


class VertexLoadedAnthropicTests(unittest.TestCase):
    def setUp(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Vertex)
        self.httpd.seen, self.httpd.queue = [], []
        self.httpd.json_body = json.dumps(MESSAGE).encode("utf-8")
        self.httpd.stream_body = STREAM
        thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        thread.start()
        self.ledger = Path(tempfile.mkdtemp())
        host, port = self.httpd.server_address
        self.proxy = start_proxy("proj", model=MODEL_ID, token="tok",
                                 upstream=f"http://{host}:{port}", ledger_dir=self.ledger)
        self.addCleanup(self.proxy.close)
        self.addCleanup(self.httpd.shutdown)
        self.addCleanup(self.httpd.server_close)

    def cell(self, cell_id, agents):
        base = cell_proxy_base(self.proxy.base_url, cell_id)
        for agent in agents:
            headers = {"User-Agent": agent} if agent is not None else {}
            status, _ = _post(base.rstrip("/") + "/v1/messages", BODY, headers)
            self.assertEqual(status, 200)
        records = [json.loads(line) for line in
                   cell_ledger_path(self.ledger, cell_id).read_text().splitlines()]
        row = apply_cell_meter({"turns": 1}, {"ledger_dir": str(self.ledger), "cell_id": cell_id},
                               protocol_model=MODEL_ID, protocol_location=LOCATION)
        return records, row

    def test_ai_sdk_user_agent_fills_ledger_and_row(self):
        records, row = self.cell("ua", ["ai-sdk/anthropic/2.0.17 ai-sdk/provider-utils/3.0.9"] * 2)
        self.assertEqual([r.get("loaded_anthropic") for r in records], ["2.0.17", "2.0.17"])
        self.assertEqual(row["loaded_anthropic"], "2.0.17")
        # The caller's UA is still not forwarded upstream.
        self.assertTrue(self.httpd.seen)

    def test_two_versions_in_one_cell_are_mixed(self):
        _records, row = self.cell("mix", ["ai-sdk/anthropic/2.0.17", "ai-sdk/anthropic/3.0.1"])
        self.assertEqual(row["loaded_anthropic"], "mixed:2.0.17,3.0.1")

    def test_missing_user_agent_stays_unproven(self):
        records, row = self.cell("none", [None, "python-urllib/3"])
        self.assertTrue(all("loaded_anthropic" not in r for r in records))
        self.assertIsNone(row["loaded_anthropic"])


if __name__ == "__main__":
    unittest.main()
