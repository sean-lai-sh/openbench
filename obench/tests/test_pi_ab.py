#!/usr/bin/env python3

import json
import os
import stat
import tempfile
import textwrap
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from thesis.ab.compat import Assessment
from thesis.ab.compat_cli import assess_cli, extra_args
from thesis.ab.durable import publish_text
from thesis.ab.errors import Incompatible
from thesis.ab.models_config import model_document, supports_custom_models
from thesis.ab.prs import parse_prs, select_prs
from thesis.ab.run_ab import drive
from thesis.ab.summarize import pr_record, render_markdown
from thesis.ab.toolchain import nvm_install_arg, pick_bun
from thesis.ab.vertex_anthropic_proxy import start_proxy, translate_body, vertex_path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "thesis" / "ab" / "fixtures" / "pi-harness-prs.csv"
SHA_A = "a" * 40
SHA_B = "b" * 40
USAGE = (
    b'{"id":"msg","usage":{"input_tokens":4,"output_tokens":5,'
    b'"cache_read_input_tokens":6,"cache_creation_input_tokens":7}}'
)


def _tree(text: str) -> Path:
    root = Path(tempfile.mkdtemp())
    src = root / "packages" / "coding-agent" / "src"
    src.mkdir(parents=True)
    (src / "models.ts").write_text(text, encoding="utf-8")
    return root


class _Stub(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):  # noqa: N802 - stdlib name
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        self.server.seen.append({
            "path": self.path,
            "body": raw,
            "beta": self.headers.get("anthropic-beta"),
            "auth": self.headers.get("Authorization"),
        })
        if self.path.endswith(":streamRawPredict"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            first = b'data: {"type":"message_start"}\n\n'
            self.wfile.write(f"{len(first):X}\r\n".encode("ascii") + first + b"\r\n")
            self.wfile.flush()
            self.server.first.set()
            if not self.server.release.wait(5):
                return
            rest = b'data: {"usage":{"cache_read_input_tokens":6}}\n\n'
            self.wfile.write(f"{len(rest):X}\r\n".encode("ascii") + rest + b"\r\n")
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(USAGE)))
        self.end_headers()
        self.wfile.write(USAGE)

    def log_message(self, fmt, *args):
        return


def _listen():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
    httpd.seen = []
    httpd.first = threading.Event()
    httpd.release = threading.Event()
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address
    return httpd, thread, f"http://{host}:{port}"


def _post(url, body, headers=None):
    request = urllib.request.Request(
        url, data=body, headers=headers or {}, method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, response.read()


class TestPiList(unittest.TestCase):
    def test_fixture_ids_and_shas(self):
        rows = parse_prs(FIXTURE)
        self.assertEqual(len(rows), 45)
        pi1 = next(row for row in rows if row.pr == "pi-1")
        self.assertEqual(pi1.repo, "badlogic/pi-mono")
        self.assertEqual(pi1.number, "1")
        self.assertEqual(pi1.without_sha, "60cea11f375b4ff263bdd80b86af26314ddc079e")
        self.assertEqual(pi1.with_sha, "29900ce647e2d2e0824e05c143e5035a67281f17")
        omp45 = next(row for row in rows if row.pr == "omp-45")
        self.assertEqual(omp45.repo, "can1357/oh-my-pi")
        self.assertEqual(omp45.with_sha, "9985b63864ee56793155051f4e933c9513835c64")
        directs = [row.pr for row in rows if row.number in {"1", "2", "3"}]
        self.assertEqual(directs, ["pi-1", "pi-2", "pi-3"])
        chosen = select_prs(rows, ["pi-3,omp-14"])
        self.assertEqual([row.pr for row in chosen], ["pi-3", "omp-14"])


class TestProxy(unittest.TestCase):
    def test_translate_strips_model_and_picks_the_vertex_method(self):
        kind, body = translate_body(
            "/v1/messages",
            b'{"model":"claude-opus-5-5","max_tokens":8,"messages":[]}',
        )
        self.assertEqual(kind, "raw")
        parsed = json.loads(body)
        self.assertEqual(parsed["anthropic_version"], "vertex-2023-10-16")
        self.assertNotIn("model", parsed)
        self.assertNotIn("stream", parsed)
        kind, streamed = translate_body(
            "/v1/messages",
            b'{"model":"claude-opus-5-5","stream":true,"messages":[]}',
        )
        self.assertEqual(kind, "stream")
        self.assertTrue(json.loads(streamed)["stream"])
        kind, _counted = translate_body("/v1/messages/count_tokens", b'{"model":"x","messages":[]}')
        self.assertEqual(kind, "count")
        self.assertEqual(
            vertex_path("proj", "claude-opus-5-5", "stream"),
            "/v1/projects/proj/locations/global/publishers/anthropic/models/claude-opus-5-5:streamRawPredict",
        )

    def test_stub_upstream_keeps_usage_and_streams_the_first_chunk(self):
        httpd, thread, upstream = _listen()
        proxy = start_proxy("proj", token="tok", upstream=upstream)
        self.addCleanup(proxy.close)
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        self.addCleanup(lambda: thread.join(timeout=2))
        status, payload = _post(
            proxy.base_url + "/v1/messages",
            b'{"model":"claude-opus-5-5","max_tokens":8,"messages":[]}',
            {"anthropic-beta": "files-api-2025-04-14", "Content-Type": "application/json"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload, USAGE)
        seen = httpd.seen[-1]
        self.assertTrue(seen["path"].endswith(":rawPredict"))
        self.assertEqual(seen["auth"], "Bearer tok")
        self.assertEqual(seen["beta"], "files-api-2025-04-14")
        forwarded = json.loads(seen["body"])
        self.assertEqual(forwarded["anthropic_version"], "vertex-2023-10-16")
        self.assertNotIn("model", forwarded)
        status, counted = _post(
            proxy.base_url + "/v1/messages/count_tokens",
            b'{"model":"claude-opus-5-5","messages":[]}',
        )
        self.assertEqual(status, 200)
        self.assertEqual(counted, USAGE)
        self.assertTrue(httpd.seen[-1]["path"].endswith(":countTokens"))

        got_first = threading.Event()
        chunks = []

        def read_stream():
            request = urllib.request.Request(
                proxy.base_url + "/v1/messages",
                data=b'{"model":"claude-opus-5-5","stream":true,"messages":[]}',
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                chunks.append(response.read(20))
                got_first.set()
                chunks.append(response.read())

        reader = threading.Thread(target=read_stream)
        reader.start()
        self.assertTrue(httpd.first.wait(3))
        self.assertTrue(got_first.wait(2))
        self.assertTrue(chunks[0].startswith(b"data: {"))
        httpd.release.set()
        reader.join(timeout=5)
        self.assertFalse(reader.is_alive())
        whole = b"".join(chunks)
        self.assertIn(b"message_start", whole)
        self.assertIn(b'"cache_read_input_tokens":6', whole)
        self.assertTrue(httpd.seen[-1]["path"].endswith(":streamRawPredict"))


class TestModelFile(unittest.TestCase):
    def test_json_and_yaml_follow_the_checkout(self):
        early = _tree("read models.json from the agent directory\n")
        body = model_document(early, "http://127.0.0.1:9", "models.json")
        provider = json.loads(body)["providers"]["vertex-anthropic"]
        self.assertEqual(provider["baseUrl"], "http://127.0.0.1:9")
        self.assertEqual(provider["api"], "anthropic-messages")
        self.assertEqual(provider["apiKey"], "proxy")
        model = provider["models"][0]
        self.assertEqual(model["id"], "claude-opus-5-5")
        self.assertEqual(model["contextWindow"], 1000000)
        self.assertEqual(model["maxTokens"], 128000)
        self.assertNotIn("compat", model)
        self.assertTrue(supports_custom_models(early))
        empty = Path(tempfile.mkdtemp())
        (empty / "packages" / "coding-agent" / "src").mkdir(parents=True)
        self.assertFalse(supports_custom_models(empty))
        later = _tree("models.yml plus supportsStrictTools on custom anthropic models\n")
        yaml = model_document(later, "http://127.0.0.1:9", "models.yml")
        self.assertIn('baseUrl: "http://127.0.0.1:9"', yaml)
        self.assertIn("supportsStrictTools: true", yaml)
        plain = model_document(early, "http://127.0.0.1:9", "models.yml")
        self.assertNotIn("supportsStrictTools", plain)


class TestHeadless(unittest.TestCase):
    def test_extra_args_come_from_help(self):
        self.assertEqual(
            extra_args("--no-session\n--approve\n--mode json\n", "pi"),
            ["--no-session", "--approve"],
        )
        self.assertEqual(extra_args("--no-session\n--mode json\n", "pi"), ["--no-session"])
        self.assertEqual(extra_args("usage: omp\n", "omp"), ["--yolo"])

    def test_toolchain_picks_a_major_or_an_exact_version(self):
        self.assertEqual(nvm_install_arg(">=22.19.0"), "22")
        self.assertEqual(nvm_install_arg("22.19.0"), "22.19.0")
        self.assertEqual(nvm_install_arg(">=20.0.0"), "20")
        self.assertEqual(pick_bun("1.3.7", ["1.3.7", "1.4.0"]), "1.3.7")
        self.assertEqual(pick_bun(">=1.4", ["1.3.9", "1.4.0", "1.5.2"]), "1.5.2")

    def _binary(self, body: str) -> Path:
        path = Path(tempfile.mkdtemp()) / "pi"
        path.write_text(body, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
        return path

    def test_vertex_run_writes_the_model_file_and_reads_usage(self):
        capture = Path(tempfile.mkdtemp()) / "capture.json"
        binary = self._binary(textwrap.dedent(f"""\
            #!/usr/bin/env python3
            import json, os, sys
            from pathlib import Path
            if "--help" in sys.argv:
                print("--no-session")
                print("--approve")
                raise SystemExit(0)
            agent = Path(os.environ.get("OMP_CODING_AGENT_DIR") or os.environ["PI_CODING_AGENT_DIR"])
            files = {{path.name: path.read_text() for path in agent.iterdir()}}
            Path({str(capture)!r}).write_text(json.dumps({{"argv": sys.argv, "files": files}}))
            usage = {{
                "input": 11, "cacheRead": 3, "cacheWrite": 2,
                "output": 7, "reasoning": 1, "totalTokens": 23,
            }}
            print(json.dumps({{
                "type": "turn_end",
                "message": {{"role": "assistant", "content": [{{"type": "text", "text": "done"}}], "usage": usage}},
            }}))
        """))
        spec = {
            "bin": str(binary),
            "proxy_url": "http://127.0.0.1:9",
            "agent_env": "PI_CODING_AGENT_DIR",
            "home_dir": ".pi",
            "models_filename": "models.json",
            "models_body": '{"providers":{"vertex-anthropic":{"baseUrl":"http://127.0.0.1:9"}}}\n',
            "extra_args": ["--no-session", "--approve"],
            "provider": "vertex-anthropic",
            "model_id": "claude-opus-5-5",
        }
        saved = os.environ.get("OBENCH_PI_VERTEX")
        os.environ["OBENCH_PI_VERTEX"] = json.dumps(spec)
        try:
            from obench.adapters.pi import run
            result = run("fix the test", "/tmp", "claude-opus-5-5", 10)
        finally:
            if saved is None:
                os.environ.pop("OBENCH_PI_VERTEX", None)
            else:
                os.environ["OBENCH_PI_VERTEX"] = saved
        self.assertTrue(result["completed"])
        self.assertIsNone(result["error"])
        self.assertEqual(result["tokens_input_uncached"], 11)
        self.assertEqual(result["tokens_cache_read"], 3)
        self.assertEqual(result["tokens_cache_write"], 2)
        self.assertEqual(result["tokens_output"], 7)
        self.assertEqual(result["model_context_window"], 1000000)
        self.assertEqual(result["model_max_tokens"], 128000)
        captured = json.loads(capture.read_text(encoding="utf-8"))
        self.assertEqual(captured["argv"], [
            str(binary), "-p", "fix the test",
            "--mode", "json",
            "--provider", "vertex-anthropic",
            "--model", "claude-opus-5-5",
            "--no-session", "--approve",
        ])
        self.assertIn("http://127.0.0.1:9", captured["files"]["models.json"])

    def test_a_trust_prompt_fails_fast(self):
        binary = self._binary(textwrap.dedent("""\
            #!/usr/bin/env python3
            import time
            print("Do you trust this project?", flush=True)
            time.sleep(30)
        """))
        spec = {
            "bin": str(binary),
            "agent_env": "PI_CODING_AGENT_DIR",
            "home_dir": ".pi",
            "models_filename": "models.json",
            "models_body": "{}",
            "extra_args": [],
            "provider": "vertex-anthropic",
            "model_id": "claude-opus-5-5",
        }
        saved = os.environ.get("OBENCH_PI_VERTEX")
        os.environ["OBENCH_PI_VERTEX"] = json.dumps(spec)
        started = time.monotonic()
        try:
            from obench.adapters.pi import run
            result = run("task", "/tmp", "claude-opus-5-5", 15)
        finally:
            if saved is None:
                os.environ.pop("OBENCH_PI_VERTEX", None)
            else:
                os.environ["OBENCH_PI_VERTEX"] = saved
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(result["error"], "waiting for input")
        self.assertFalse(result["completed"])

    def test_omp_run_uses_models_yml(self):
        capture = Path(tempfile.mkdtemp()) / "capture.json"
        binary = self._binary(textwrap.dedent(f"""\
            #!/usr/bin/env python3
            import json, os
            from pathlib import Path
            agent = Path(os.environ["OMP_CODING_AGENT_DIR"])
            Path({str(capture)!r}).write_text(agent.joinpath("models.yml").read_text())
            print(json.dumps({{"type": "turn_end", "message": {{"usage": {{
                "input": 1, "cacheRead": 0, "cacheWrite": 0, "output": 1,
                "reasoning": 0, "totalTokens": 2,
            }}}}}}))
        """))
        spec = {
            "bin": str(binary),
            "agent_env": "OMP_CODING_AGENT_DIR",
            "home_dir": ".omp",
            "models_filename": "models.yml",
            "models_body": "providers:\n  vertex-anthropic:\n    baseUrl: \"http://127.0.0.1:9\"\n",
            "extra_args": ["--yolo"],
            "provider": "vertex-anthropic",
            "model_id": "claude-opus-5-5",
        }
        saved = os.environ.get("OBENCH_PI_VERTEX")
        os.environ["OBENCH_PI_VERTEX"] = json.dumps(spec)
        try:
            from obench.adapters.omp import NAME, run
            self.assertEqual(NAME, "omp")
            result = run("task", "/tmp", "claude-opus-5-5", 10)
        finally:
            if saved is None:
                os.environ.pop("OBENCH_PI_VERTEX", None)
            else:
                os.environ["OBENCH_PI_VERTEX"] = saved
        self.assertTrue(result["completed"])
        self.assertIn("http://127.0.0.1:9", capture.read_text(encoding="utf-8"))
        self.assertEqual(result["cmd"][-1], "--yolo")

    def test_assess_cli_reads_help_and_the_tree(self):
        binary = self._binary("#!/bin/sh\nprintf '%s\\n' '--no-session' '--approve'\n")
        root = _tree("load models.json\n")
        assessment = assess_cli(str(binary), root, "pi", "http://127.0.0.1:9")
        self.assertEqual(assessment.status, "configured")
        self.assertEqual(assessment.harness, "pi")
        self.assertEqual(assessment.vertex["extra_args"], ["--no-session", "--approve"])
        self.assertIn('"id": "claude-opus-5-5"', assessment.vertex["models_body"])
        missing = assess_cli(str(Path(tempfile.mkdtemp()) / "absent"), root, "pi", "http://127.0.0.1:9")
        self.assertEqual(missing.status, "incompatible")
        self.assertEqual(missing.reason, "could not read --help")


class TestPiDrive(unittest.TestCase):
    def _rows(self, repo):
        import csv
        path = Path(tempfile.mkdtemp()) / "prs.csv"
        header = [
            "Repo", "#", "PR", "Title", "Category", "Harness change",
            "Merge commit SHA", "Parent/base SHA",
        ]
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=header)
            writer.writeheader()
            writer.writerow({
                "Repo": repo,
                "#": "3",
                "PR": "direct",
                "Title": "Identity",
                "Category": "prompt",
                "Harness change": "Removes the identity line.",
                "Merge commit SHA": SHA_B,
                "Parent/base SHA": SHA_A,
            })
        return parse_prs(path)

    def test_repo_selects_the_harness_and_an_incompatible_build_is_not_scored(self):
        out = Path(tempfile.mkdtemp())
        seen = []

        def worker(spec):
            seen.append(spec["harness"])
            publish_text(Path(spec["cell_path"]), json.dumps({
                "task": spec["task"], "trial": spec["trial"], "score": 1, "success": True,
                "tokens_input_uncached": 1, "tokens_output": 1,
                "tokens_cache_read": 0, "tokens_cache_write": 0,
            }))

        def build_fn(sha, cache, repo=""):
            if sha == SHA_A:
                raise Incompatible("no custom-model support")
            return Path("/tmp") / sha

        def assess_fn(binary):
            return Assessment("configured", "proxy", {}, False)

        rows = self._rows("badlogic/pi-mono")
        drive(
            rows, ("make-it-run",), 1, out,
            jobs=1, model="claude-opus-5-5", timeout_s=5, cache=out,
            max_cost_usd=None, dry_run=False, tasks_dir=Path("/tmp"),
            build_fn=build_fn, assess_fn=assess_fn, worker=worker,
        )
        self.assertEqual(seen, ["pi"])
        sidecar = json.loads((out / "pi-3" / "without.incompatible.json").read_text(encoding="utf-8"))
        self.assertEqual(sidecar["status"], "incompatible")
        self.assertEqual(sidecar["reason"], "no custom-model support")
        self.assertEqual(sidecar["sha"], SHA_A)
        text = render_markdown([pr_record(rows[0], out)])
        self.assertTrue(text.startswith("# Harness A/B"))
        self.assertIn("Repo: badlogic/pi-mono", text)
        self.assertIn("without is incompatible: no custom-model support", text)


if __name__ == "__main__":
    unittest.main()
