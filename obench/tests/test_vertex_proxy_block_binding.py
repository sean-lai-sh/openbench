import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from thesis.ab.vertex_anthropic_proxy import (
    BLOCK_BINDING_ENV,
    ENV_CAUSE_THINKING_SIGNATURE,
    apply_block_binding,
    cell_ledger_path,
    env_cause_for_status,
    prepare_thinking_blocks,
    start_proxy,
    thinking_block_binding_setting,
)

USAGE = b'{"id":"msg","usage":{"input_tokens":4,"output_tokens":5}}'
SIGNATURE = (
    b'{"type":"error","error":{"type":"invalid_request_error",'
    b'"message":"Invalid signature in thinking block"}}'
)
OTHER_400 = b'{"type":"error","error":{"type":"invalid_request_error","message":"temperature is deprecated"}}'


def _body(with_thinking=True, thinking=None, redacted=False):
    content = [{"type": "text", "text": "answer"}]
    if with_thinking:
        content.insert(0, {"type": "thinking", "thinking": "x", "signature": "s"})
    if redacted:
        content.insert(0, {"type": "redacted_thinking", "data": "abc"})
    body = {
        "model": "claude-opus-5-5",
        "max_tokens": 8,
        "messages": [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": content},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]},
        ],
    }
    if thinking is not None:
        body["thinking"] = thinking
    return body


def _types(body):
    found = []
    for message in body.get("messages") or []:
        content = message.get("content")
        if isinstance(content, list):
            found.append([block.get("type") for block in content if isinstance(block, dict)])
        else:
            found.append(content)
    return found


class _Stub(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):  # noqa: N802 - stdlib name
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        self.server.seen.append({
            "path": self.path,
            "body": raw,
            "beta": self.headers.get("anthropic-beta"),
        })
        if b'"force-signature"' in raw:
            status, payload = 400, SIGNATURE
        elif b'"force-other"' in raw:
            status, payload = 400, OTHER_400
        else:
            status, payload = 200, USAGE
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        return


def _listen():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
    httpd.seen = []
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address
    return httpd, thread, f"http://{host}:{port}"


def _post(url, body):
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _rows(ledger: Path, cell: str) -> list:
    return [
        json.loads(line)
        for line in cell_ledger_path(ledger, cell).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class BlockBindingTests(unittest.TestCase):
    def test_off_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(BLOCK_BINDING_ENV, None)
            body = _body()
            self.assertEqual(thinking_block_binding_setting(), "off")
            self.assertIsNone(apply_block_binding(body))
            prepared = prepare_thinking_blocks(body)
            self.assertEqual(prepared, {
                "thinking_block_binding": "off",
                "thinking_blocks_stripped": 0,
                "binding": None,
            })
            self.assertNotIn("thinking", body)
            self.assertEqual(_types(body)[1], ["thinking", "text"])

    def test_unknown_value_stays_off(self):
        with mock.patch.dict(os.environ, {BLOCK_BINDING_ENV: "strip"}):
            body = _body()
            self.assertEqual(thinking_block_binding_setting(), "off")
            self.assertEqual(prepare_thinking_blocks(body)["thinking_blocks_stripped"], 0)
            self.assertEqual(_types(body)[1], ["thinking", "text"])

    def test_drop_block_strips_when_thinking_is_disabled(self):
        with mock.patch.dict(os.environ, {BLOCK_BINDING_ENV: "drop_block"}):
            body = _body(redacted=True)
            self.assertIsNone(apply_block_binding(body))
            self.assertNotIn("thinking", body)
            prepared = prepare_thinking_blocks(body)
            self.assertEqual(prepared["thinking_block_binding"], "drop_block")
            self.assertEqual(prepared["thinking_blocks_stripped"], 2)
            self.assertIsNone(prepared["binding"])
            self.assertNotIn("thinking", body)
            self.assertEqual(_types(body), ["q", ["text"], ["tool_result"]])

    def test_drop_block_drops_a_thinking_only_message(self):
        with mock.patch.dict(os.environ, {BLOCK_BINDING_ENV: "drop_block"}):
            body = {
                "messages": [
                    {"role": "user", "content": "q"},
                    {"role": "assistant", "content": [
                        {"type": "thinking", "thinking": "only", "signature": "s"},
                    ]},
                ],
            }
            self.assertEqual(prepare_thinking_blocks(body)["thinking_blocks_stripped"], 1)
            self.assertEqual(body["messages"], [{"role": "user", "content": "q"}])

    def test_drop_block_keeps_history_when_thinking_is_enabled(self):
        with mock.patch.dict(os.environ, {BLOCK_BINDING_ENV: "drop_block"}):
            body = _body(thinking={"type": "adaptive", "x": 1}, redacted=True)
            prepared = prepare_thinking_blocks(body)
            self.assertEqual(prepared["binding"], "drop_block")
            self.assertEqual(prepared["thinking_blocks_stripped"], 0)
            self.assertEqual(body["thinking"], {
                "type": "adaptive",
                "x": 1,
                "block_binding": {"prefix_mismatch_behavior": "drop_block"},
            })
            self.assertEqual(_types(body)[1], ["redacted_thinking", "thinking", "text"])
            budget = _body(thinking={"type": "enabled", "budget_tokens": 128})
            self.assertEqual(apply_block_binding(budget), "drop_block")
            self.assertEqual(budget["thinking"]["budget_tokens"], 128)
            self.assertIn("block_binding", budget["thinking"])
            self.assertEqual(_types(budget)[1], ["thinking", "text"])

    def test_enabled_without_history_thinking_is_untouched(self):
        with mock.patch.dict(os.environ, {BLOCK_BINDING_ENV: "drop_block"}):
            body = _body(with_thinking=False, thinking={"type": "adaptive"})
            self.assertIsNone(apply_block_binding(body))
            self.assertEqual(body["thinking"], {"type": "adaptive"})
            self.assertEqual(prepare_thinking_blocks(body)["thinking_blocks_stripped"], 0)

    def test_signature_cause_is_only_that_400(self):
        self.assertEqual(
            env_cause_for_status(400, SIGNATURE.decode()),
            ENV_CAUSE_THINKING_SIGNATURE,
        )
        self.assertIsNone(env_cause_for_status(400, OTHER_400.decode()))
        self.assertIsNone(env_cause_for_status(500, SIGNATURE.decode()))
        self.assertIsNone(env_cause_for_status(400, "overloaded"))
        self.assertIsNone(env_cause_for_status(True, SIGNATURE.decode()))


class ThinkingBlockProxyTests(unittest.TestCase):
    def setUp(self):
        self.httpd, self.thread, self.upstream = _listen()
        self.ledger = Path(tempfile.mkdtemp())
        self.addCleanup(self.httpd.shutdown)
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(lambda: self.thread.join(timeout=2))

    def _proxy(self):
        proxy = start_proxy(
            "proj", token="tok", upstream=self.upstream, ledger_dir=self.ledger,
        )
        self.addCleanup(proxy.close)
        return proxy

    def test_default_forwards_thinking_blocks(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(BLOCK_BINDING_ENV, None)
            proxy = self._proxy()
            body = _body(redacted=True)
            status, _payload = _post(proxy.base_url + "/c/off/v1/messages", body)
        self.assertEqual(status, 200)
        forwarded = json.loads(self.httpd.seen[-1]["body"])
        self.assertNotIn("thinking", forwarded)
        self.assertEqual(_types(forwarded)[1], ["redacted_thinking", "thinking", "text"])
        self.assertNotIn("thinking-binding", self.httpd.seen[-1]["beta"] or "")
        row = _rows(self.ledger, "off")[0]
        self.assertEqual(row["thinking_block_binding"], "off")
        self.assertEqual(row["thinking_blocks_stripped"], 0)
        self.assertEqual(row["thinking_sent"], "none")
        self.assertEqual(row["requested_model"], "claude-opus-5-5")
        self.assertEqual(row["endpoint_location"], "global")
        self.assertNotIn("env_cause", row)

    def test_drop_block_strips_a_thinking_off_request_and_records_the_count(self):
        with mock.patch.dict(os.environ, {BLOCK_BINDING_ENV: "drop_block"}):
            proxy = self._proxy()
            body = _body(redacted=True)
            status, _payload = _post(proxy.base_url + "/c/strip/v1/messages", body)
        self.assertEqual(status, 200)
        forwarded = json.loads(self.httpd.seen[-1]["body"])
        self.assertNotIn("thinking", forwarded)
        self.assertEqual(_types(forwarded), ["q", ["text"], ["tool_result"]])
        self.assertNotIn("signature", self.httpd.seen[-1]["body"].decode())
        self.assertNotIn("thinking-binding", self.httpd.seen[-1]["beta"] or "")
        row = _rows(self.ledger, "strip")[0]
        self.assertEqual(row["thinking_block_binding"], "drop_block")
        self.assertEqual(row["thinking_blocks_stripped"], 2)
        self.assertEqual(row["thinking_sent"], "none")

    def test_drop_block_leaves_an_enabled_thinking_request_bound(self):
        with mock.patch.dict(os.environ, {BLOCK_BINDING_ENV: "drop_block"}):
            proxy = self._proxy()
            body = _body(thinking={"type": "adaptive", "x": 1}, redacted=True)
            status, _payload = _post(proxy.base_url + "/c/on/v1/messages", body)
        self.assertEqual(status, 200)
        forwarded = json.loads(self.httpd.seen[-1]["body"])
        self.assertEqual(forwarded["thinking"]["type"], "adaptive")
        self.assertEqual(forwarded["thinking"]["x"], 1)
        self.assertEqual(
            forwarded["thinking"]["block_binding"],
            {"prefix_mismatch_behavior": "drop_block"},
        )
        self.assertEqual(_types(forwarded)[1], ["redacted_thinking", "thinking", "text"])
        self.assertIn("thinking-binding-controls-2026-08-01", self.httpd.seen[-1]["beta"])
        row = _rows(self.ledger, "on")[0]
        self.assertEqual(row["thinking_block_binding"], "drop_block")
        self.assertEqual(row["thinking_blocks_stripped"], 0)
        self.assertEqual(row["thinking_sent"], "adaptive")
        self.assertEqual(row["cc_identity_stripped"]["thinking_block_binding"], "drop_block")

    def test_signature_400_is_tagged_and_another_400_is_not(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(BLOCK_BINDING_ENV, None)
            proxy = self._proxy()
            signature = _body()
            signature["messages"][0]["content"] = "force-signature"
            other = _body(with_thinking=False)
            other["messages"][0]["content"] = "force-other"
            sig_status, _sig = _post(proxy.base_url + "/c/err/v1/messages", signature)
            other_status, _other = _post(proxy.base_url + "/c/err/v1/messages", other)
        self.assertEqual((sig_status, other_status), (400, 400))
        # Default off still forwards the thinking block. The 400 is tagged anyway.
        forwarded = json.loads(self.httpd.seen[0]["body"])
        self.assertIn("thinking", [block.get("type") for block in forwarded["messages"][1]["content"]])
        rows = _rows(self.ledger, "err")
        self.assertEqual(rows[0]["env_cause"], ENV_CAUSE_THINKING_SIGNATURE)
        self.assertEqual(rows[0]["status"], 400)
        self.assertEqual(rows[0]["thinking_block_binding"], "off")
        self.assertNotIn("env_cause", rows[1])
        self.assertIn("temperature", rows[1]["error"])

    def test_remaining_signature_400_is_tagged_when_stripping_is_on(self):
        with mock.patch.dict(os.environ, {BLOCK_BINDING_ENV: "drop_block"}):
            proxy = self._proxy()
            body = _body(thinking={"type": "enabled", "budget_tokens": 64})
            body["messages"][0]["content"] = "force-signature"
            status, _payload = _post(proxy.base_url + "/c/remain/v1/messages", body)
        self.assertEqual(status, 400)
        forwarded = json.loads(self.httpd.seen[-1]["body"])
        self.assertEqual(
            [block.get("type") for block in forwarded["messages"][1]["content"]],
            ["thinking", "text"],
        )
        row = _rows(self.ledger, "remain")[0]
        self.assertEqual(row["env_cause"], ENV_CAUSE_THINKING_SIGNATURE)
        self.assertEqual(row["thinking_blocks_stripped"], 0)
        self.assertEqual(row["thinking_sent"], "enabled+budget_tokens")


class ThinkingBlockCellTests(unittest.TestCase):
    def test_every_cell_records_the_setting_and_only_the_signature_cause(self):
        from thesis.ab.run_ab import apply_cell_meter, attach_thinking
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(BLOCK_BINDING_ENV, None)
            empty = attach_thinking({"task": "filter-js-from-html"}, "default", [])
        self.assertEqual(empty["thinking_block_binding"], "off")
        self.assertEqual(empty["thinking_blocks_stripped"], 0)
        self.assertNotIn("env_cause", empty)

        ledger = Path(tempfile.mkdtemp())
        cell_ledger_path(ledger, "cell").write_text("\n".join([
            json.dumps({
                "record_type": "request",
                "status": 400,
                "error": SIGNATURE.decode(),
                "thinking_block_binding": "drop_block",
                "thinking_blocks_stripped": 3,
                "thinking_sent": "none",
                "env_cause": ENV_CAUSE_THINKING_SIGNATURE,
            }),
            json.dumps({
                "record_type": "request",
                "status": 400,
                "error": OTHER_400.decode(),
                "thinking_block_binding": "drop_block",
                "thinking_blocks_stripped": 0,
                "thinking_sent": "none",
            }),
        ]) + "\n", encoding="utf-8")
        metered = apply_cell_meter({}, {"ledger_dir": str(ledger), "cell_id": "cell"})
        self.assertEqual(metered["thinking_block_binding"], "drop_block")
        self.assertEqual(metered["thinking_blocks_stripped"], 3)
        self.assertEqual(metered["env_cause"], ENV_CAUSE_THINKING_SIGNATURE)
        self.assertEqual(metered["requests_error"], 2)
        recorded = attach_thinking({"task": "filter-js-from-html"}, "off", [
            json.loads(line)
            for line in cell_ledger_path(ledger, "cell").read_text(encoding="utf-8").splitlines()
        ])
        self.assertEqual(recorded["thinking_block_binding"], "drop_block")
        self.assertEqual(recorded["thinking_blocks_stripped"], 3)
        self.assertEqual(recorded["env_cause"], ENV_CAUSE_THINKING_SIGNATURE)

        other = Path(tempfile.mkdtemp())
        cell_ledger_path(other, "plain").write_text(json.dumps({
            "record_type": "request",
            "status": 400,
            "error": "bad request",
            "thinking_block_binding": "off",
            "thinking_blocks_stripped": 0,
        }) + "\n", encoding="utf-8")
        plain = apply_cell_meter({}, {"ledger_dir": str(other), "cell_id": "plain"})
        self.assertEqual(plain["thinking_block_binding"], "off")
        self.assertNotIn("env_cause", plain)
        self.assertEqual(plain["failure_class"], "infra")


class ThinkingBlockFlagTests(unittest.TestCase):
    def test_flag_sets_the_env_only_for_the_run(self):
        from thesis.ab.run_ab import main
        out = Path(tempfile.mkdtemp())
        csv_path = out / "prs.jsonl"
        csv_path.write_text(json.dumps({
            "pr": "3052",
            "after_sha": "b" * 40,
            "before_sha": "a" * 40,
        }) + "\n", encoding="utf-8")
        captured = {}

        def fake_drive(*args, **kwargs):
            captured["during"] = os.environ.get(BLOCK_BINDING_ENV)
            return "plan\n", 0, None

        argv = [
            str(csv_path), "--pr", "3052", "--dry-run",
            "--tasks", "make-it-run", "--out", str(out / "run"),
        ]
        saved = os.environ.get(BLOCK_BINDING_ENV)
        os.environ.pop(BLOCK_BINDING_ENV, None)
        try:
            with mock.patch("thesis.ab.run_ab.drive", fake_drive), redirect_stdout(io.StringIO()):
                code = main(argv + ["--thinking-block-binding", "drop_block"])
            self.assertEqual(code, 0)
            self.assertEqual(captured["during"], "drop_block")
            self.assertNotIn(BLOCK_BINDING_ENV, os.environ)

            os.environ[BLOCK_BINDING_ENV] = "drop_block"
            with mock.patch("thesis.ab.run_ab.drive", fake_drive), redirect_stdout(io.StringIO()):
                code = main(argv + ["--thinking-block-binding", "off"])
            self.assertEqual(code, 0)
            self.assertIsNone(captured["during"])
            self.assertEqual(os.environ.get(BLOCK_BINDING_ENV), "drop_block")

            with mock.patch("thesis.ab.run_ab.drive", fake_drive), redirect_stdout(io.StringIO()):
                code = main(argv)
            self.assertEqual(code, 0)
            self.assertEqual(captured["during"], "drop_block")
            self.assertEqual(os.environ.get(BLOCK_BINDING_ENV), "drop_block")
        finally:
            if saved is None:
                os.environ.pop(BLOCK_BINDING_ENV, None)
            else:
                os.environ[BLOCK_BINDING_ENV] = saved

        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            main([str(csv_path), "--thinking-block-binding", "strip"])
        self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
