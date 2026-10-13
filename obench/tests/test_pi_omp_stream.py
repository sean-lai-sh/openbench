"""Recorded omp --mode json streams and the Vertex cell ledger."""

import contextlib
import io
import json
import os
import stat
import subprocess
import tarfile
import tempfile
import textwrap
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from obench import failure_class
from obench.final_answer import extract_final_answer
from obench.run import apply_proxy_ledger
from thesis.ab.build_omp import (
    PINNED_BUN,
    bun_version_for_build,
    compile_tree,
    has_unreleased_native_changes,
    native_asset_candidates,
    native_asset_name,
    next_published_natives,
    npm_native_specs,
    plan_natives,
    prepare_natives,
)
from thesis.ab.errors import BuildError
from thesis.ab.evidence import (
    attach_cell_metrics,
    bash_call_count,
    edit_call_count,
    read_call_stats,
)
from thesis.ab.run_ab import apply_cell_meter, bind_cell_proxy
from thesis.ab.toolchain import bun_requirement
from thesis.ab.vertex_anthropic_proxy import cell_ledger_path, start_proxy


def _dump(event: dict) -> str:
    return json.dumps(event)


def _assistant(content, stop="stop", error=None, usage=None) -> dict:
    message = {"role": "assistant", "content": content, "stopReason": stop}
    if error is not None:
        message["errorMessage"] = error
    if usage is not None:
        message["usage"] = usage
    return message


def _recorded_omp_run() -> str:
    """One omp --mode json run: read, edit, and bash, each copied across events."""
    read = {
        "type": "toolCall",
        "id": "read-1",
        "name": "read",
        "arguments": {"path": "src/app.py", "offset": 1, "limit": 20},
    }
    edit = {
        "type": "toolCall",
        "id": "edit-1",
        "name": "edit",
        "arguments": {"path": "src/app.py"},
    }
    bash = {
        "type": "toolCall",
        "id": "bash-1",
        "name": "bash",
        "arguments": {"command": "pytest -q"},
    }
    usage = {
        "input": 11, "cacheRead": 0, "cacheWrite": 0,
        "output": 7, "reasoning": 0, "totalTokens": 18,
    }
    first = _assistant(
        [{"type": "text", "text": "Looking at the parser."}, read, edit, bash],
        stop="toolUse",
        usage=usage,
    )
    final = _assistant(
        [
            {"type": "text", "text": "earlier note"},
            {"type": "text", "text": "patched the parser"},
        ],
        stop="stop",
    )
    lines = []
    for message in (first, final):
        lines.append(_dump({"type": "message_end", "message": message}))
        lines.append(_dump({"type": "turn_end", "message": message}))
    lines.append(_dump({
        "type": "agent_end",
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "fix it"}]},
            first,
            final,
        ],
    }))
    return "\n".join(lines) + "\n"


PROVIDER_400 = (
    '400 {"type":"error","error":{"type":"invalid_request_error",'
    '"message":"bad request"}}'
)


def _recorded_provider_400() -> str:
    message = _assistant(
        [{"type": "text", "text": "could not call the model"}],
        stop="error",
        error=PROVIDER_400,
    )
    return "\n".join([
        _dump({"type": "message_end", "message": message}),
        _dump({"type": "turn_end", "message": message}),
        _dump({"type": "agent_end", "messages": [message]}),
    ]) + "\n"


def _post(url, body):
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


class _StatusUpstream(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        if b"bad-request" in body:
            payload = (
                b'{"type":"error","error":{"message":"bad request"}}'
                + b"x" * 600
            )
            status = 400
        else:
            payload = b'{"id":"msg","usage":{"input_tokens":1,"output_tokens":1}}'
            status = 200
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        return


class PiOmpStreamTests(unittest.TestCase):
    def test_cell_proxy_rewrites_the_pi_models_body(self):
        body = json.dumps({
            "providers": {"vertex-anthropic": {"baseUrl": "http://127.0.0.1:9"}},
        })
        filled = bind_cell_proxy({
            "vertex": {
                "proxy_url": "http://127.0.0.1:9",
                "models_body": body,
            },
        }, Path("/tmp/ledger"))
        base = filled["proxy"]["base_url"]
        self.assertTrue(base.startswith("http://127.0.0.1:9/c/"))
        self.assertNotIn("/v1", base)
        parsed = json.loads(filled["vertex"]["models_body"])
        self.assertEqual(parsed["providers"]["vertex-anthropic"]["baseUrl"], base)
        self.assertEqual(filled["vertex"]["proxy_url"], base)
        self.assertEqual(filled["proxy"]["ledger_dir"], "/tmp/ledger")
        self.assertEqual(len(filled["proxy"]["cell_id"]), 16)
        self.assertEqual(
            filled["cell_ledger"],
            str(cell_ledger_path(Path("/tmp/ledger"), filled["proxy"]["cell_id"])),
        )

    def test_recorded_omp_run_counts_tools_once_and_keeps_the_last_text(self):
        root = Path(tempfile.mkdtemp())
        path = root / "agent-output.txt"
        raw = _recorded_omp_run()
        path.write_text(raw, encoding="utf-8")
        reads, reread = read_call_stats([path])
        self.assertEqual(reads, 1)
        self.assertFalse(reread)
        self.assertEqual(edit_call_count([path]), 1)
        self.assertEqual(bash_call_count([path]), 1)
        row = {}
        attach_cell_metrics(row, root, [path])
        self.assertEqual(row["read_calls"], 1)
        self.assertEqual(row["edit_calls"], 1)
        self.assertEqual(row["bash_calls"], 1)
        self.assertEqual(row["final_answer_source"], "json")
        self.assertEqual(row["final_answer_present"], True)
        self.assertTrue(row["final_answer_complete"])
        self.assertEqual(extract_final_answer(raw), "patched the parser")

    def test_pi_write_counts_as_an_edit(self):
        path = Path(tempfile.mkdtemp()) / "agent-output.txt"
        message = _assistant([{
            "type": "toolCall",
            "id": "write-1",
            "name": "write",
            "arguments": {"path": "src/out.py"},
        }])
        path.write_text(
            _dump({"type": "turn_end", "message": message}) + "\n",
            encoding="utf-8",
        )
        self.assertEqual(edit_call_count([path]), 1)
        self.assertEqual(bash_call_count([path]), 0)

    def test_opencode_tool_lines_stay_on_the_old_counter(self):
        root = Path(tempfile.mkdtemp())
        path = root / "agent-output.txt"
        path.write_text(
            "\n".join([
                '{"tool":"read","filePath":"a.py"}',
                '{"tool":"edit"}',
                '{"tool":"bash"}',
            ]) + "\n",
            encoding="utf-8",
        )
        self.assertEqual(read_call_stats([path])[0], 1)
        self.assertEqual(edit_call_count([path]), 1)
        self.assertIsNone(bash_call_count([path]))
        row = {}
        attach_cell_metrics(row, root, [path])
        self.assertNotIn("bash_calls", row)
        self.assertEqual(row["final_answer_source"], "stdout")
        self.assertEqual(row["read_calls"], 1)
        self.assertEqual(row["edit_calls"], 1)

    def test_provider_400_exits_zero_and_classifies_as_infra(self):
        raw = _recorded_provider_400()
        capture = Path(tempfile.mkdtemp()) / "capture.json"
        binary = Path(tempfile.mkdtemp()) / "omp"
        binary.write_text(textwrap.dedent(f"""\
            #!/usr/bin/env python3
            import pathlib, sys
            pathlib.Path({str(capture)!r}).write_text("ran")
            sys.stdout.write({raw!r})
            raise SystemExit(0)
        """), encoding="utf-8")
        binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
        spec = {
            "bin": str(binary),
            "proxy_url": "http://127.0.0.1:9",
            "agent_env": "PI_CODING_AGENT_DIR",
            "home_dir": ".omp",
            "models_filename": "models.yml",
            "models_body": "providers: {}\n",
            "extra_args": ["--yolo"],
            "provider": "vertex-anthropic",
            "model_id": "claude-opus-5-5",
        }
        saved = os.environ.get("OBENCH_PI_VERTEX")
        os.environ.pop("OBENCH_PI_SESSION_DIR", None)
        os.environ["OBENCH_PI_VERTEX"] = json.dumps(spec)
        try:
            from obench.adapters.pi import run
            result = run("fix the test", "/tmp", "claude-opus-5-5", 10)
        finally:
            if saved is None:
                os.environ.pop("OBENCH_PI_VERTEX", None)
            else:
                os.environ["OBENCH_PI_VERTEX"] = saved
        self.assertFalse(result["completed"])
        self.assertEqual(result["error"], PROVIDER_400)
        self.assertGreaterEqual(result["replies_error"], 1)
        self.assertEqual(result["provider_error"], PROVIDER_400)
        row = {
            "success": True,
            "completed": result["completed"],
            "checker_exit": 0,
            "replies_error": result["replies_error"],
            "full_output": result["full_output"],
        }
        self.assertEqual(failure_class.classify_failure(row, result["full_output"]), "infra")
        self.assertEqual(row["provider_error"], PROVIDER_400)

    def test_session_jsonl_stays_under_the_transcripts_dir(self):
        session = Path(tempfile.mkdtemp()) / "session"
        binary = Path(tempfile.mkdtemp()) / "omp"
        binary.write_text(textwrap.dedent("""\
            #!/usr/bin/env python3
            import json, sys
            from pathlib import Path
            if "--session-dir" not in sys.argv:
                raise SystemExit("missing session dir")
            dest = Path(sys.argv[sys.argv.index("--session-dir") + 1])
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "session.jsonl").write_text("kept\\n", encoding="utf-8")
            print(json.dumps({
                "type": "turn_end",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "done"}],
                    "stopReason": "stop",
                },
            }))
        """), encoding="utf-8")
        binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
        spec = {
            "bin": str(binary),
            "extra_args": ["--no-session", "--approve"],
            "provider": "vertex-anthropic",
            "model_id": "claude-opus-5-5",
            "models_body": "{}\n",
        }
        saved_vertex = os.environ.get("OBENCH_PI_VERTEX")
        saved_session = os.environ.get("OBENCH_PI_SESSION_DIR")
        os.environ["OBENCH_PI_VERTEX"] = json.dumps(spec)
        os.environ["OBENCH_PI_SESSION_DIR"] = str(session)
        try:
            from obench.adapters.pi import run
            result = run("fix the test", "/tmp", "claude-opus-5-5", 10)
        finally:
            if saved_vertex is None:
                os.environ.pop("OBENCH_PI_VERTEX", None)
            else:
                os.environ["OBENCH_PI_VERTEX"] = saved_vertex
            if saved_session is None:
                os.environ.pop("OBENCH_PI_SESSION_DIR", None)
            else:
                os.environ["OBENCH_PI_SESSION_DIR"] = saved_session
        self.assertTrue(result["completed"])
        self.assertNotIn("--no-session", result["cmd"])
        self.assertIn("--session-dir", result["cmd"])
        self.assertEqual(result["cmd"][result["cmd"].index("--session-dir") + 1], str(session))
        self.assertEqual((session / "session.jsonl").read_text(encoding="utf-8"), "kept\n")
        self.assertIn("done", (session.parent / "agent-output.txt").read_text(encoding="utf-8"))

    def test_ledger_non_2xx_is_infra_and_429_stays_rate_limited(self):
        solved = {
            "success": True, "completed": True, "checker_exit": 0,
            "tokens_output": 20, "turns": 2, "ledger_statuses": [400],
        }
        self.assertEqual(failure_class.classify_failure(solved), "infra")
        self.assertEqual(solved["provider_error"], "HTTP 400")
        limited = {"success": True, "completed": True, "checker_exit": 0, "ledger_statuses": [429]}
        self.assertEqual(failure_class.classify_failure(limited), "rate_limited")
        mixed = {"success": False, "ledger_statuses": [400, 429]}
        self.assertEqual(failure_class.classify_failure(mixed), "infra")
        clean = {"success": True, "completed": True, "checker_exit": 0, "ledger_statuses": [200, 200]}
        self.assertEqual(failure_class.classify_failure(clean), "solved")
        self.assertNotIn("provider_error", clean)
        judged = {
            "failure_class": "wrong_answer",
            "success": False,
            "completed": True,
            "checker_exit": 1,
            "tokens_output": 1000,
            "turns": 5,
            "ledger_statuses": [500],
        }
        self.assertEqual(failure_class.class_for_report(judged), "infra")
        stalled = {"failure_class": "stalled", "success": False, "ledger_statuses": [400]}
        self.assertEqual(failure_class.class_for_report(stalled), "stalled")
        body = {"success": True, "ledger": [{"status": 400, "error": "bad request"}]}
        self.assertEqual(failure_class.classify_failure(body), "infra")
        self.assertEqual(body["provider_error"], "bad request")

    def test_apply_proxy_ledger_counts_errors_only_when_present(self):
        clean = {}
        apply_proxy_ledger(clean, [{
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "status": 200,
        }])
        self.assertNotIn("requests_error", clean)
        self.assertNotIn("ledger_statuses", clean)
        self.assertNotIn("provider_error", clean)
        failed = {}
        apply_proxy_ledger(failed, [
            {"usage": {"input_tokens": 1, "output_tokens": 1}, "status": 200},
            {"status": 400, "error": "bad request"},
        ])
        self.assertEqual(failed["requests_error"], 1)
        self.assertEqual(failed["ledger_statuses"], [400])
        self.assertEqual(failed["provider_error"], "bad request")
        self.assertEqual(failed["tokens_proxy_calls"], 1)

    def test_apply_cell_meter_reclassifies_a_ledger_400(self):
        ledger = Path(tempfile.mkdtemp())
        path = cell_ledger_path(ledger, "cellpi")
        path.write_text(
            json.dumps({
                "record_type": "request", "status": 400, "error": "bad request",
            }) + "\n",
            encoding="utf-8",
        )
        row = {
            "success": True,
            "failure_class": "solved",
            "completed": True,
            "checker_exit": 0,
        }
        apply_cell_meter(row, {"ledger_dir": str(ledger), "cell_id": "cellpi"})
        self.assertEqual(row["requests_error"], 1)
        self.assertEqual(row["requests_count"], 1)
        self.assertEqual(row["failure_class"], "infra")
        self.assertEqual(row["provider_error"], "bad request")
        self.assertEqual(row["failure_reason"], "bad request")

    def test_requests_count_includes_failed_rows_and_is_zero_for_an_empty_ledger(self):
        ledger = Path(tempfile.mkdtemp())
        cell_ledger_path(ledger, "allfail").write_text(
            "\n".join([
                json.dumps({"record_type": "request", "status": 500, "error": "nope"}),
                json.dumps({"record_type": "request", "status": 400, "error": "bad request"}),
            ]) + "\n",
            encoding="utf-8",
        )
        failed = {"success": False, "completed": True, "failure_class": "wrong_answer"}
        apply_cell_meter(failed, {"ledger_dir": str(ledger), "cell_id": "allfail"})
        self.assertEqual(failed["requests_count"], 2)
        self.assertEqual(failed["requests_error"], 2)
        self.assertIsNotNone(failed["requests_count"])

        mixed_path = cell_ledger_path(ledger, "mixed")
        mixed_path.write_text(
            "\n".join([
                json.dumps({
                    "record_type": "request",
                    "status": 200,
                    "usage": {"input_tokens": 3, "output_tokens": 4},
                }),
                json.dumps({"record_type": "request", "status": 529, "error": "overloaded"}),
            ]) + "\n",
            encoding="utf-8",
        )
        mixed = {
            "tokens_input_uncached": 1,
            "tokens_output": 1,
            "tokens_cache_read": 0,
            "tokens_cache_write": 0,
            "token_basis": "vendor_split",
        }
        apply_cell_meter(mixed, {"ledger_dir": str(ledger), "cell_id": "mixed"})
        self.assertEqual(mixed["requests_count"], 2)
        self.assertEqual(mixed["requests_error"], 1)
        self.assertEqual(mixed["tokens_proxy_calls"], 1)

        empty = Path(tempfile.mkdtemp())
        cell_ledger_path(empty, "empty").write_text("", encoding="utf-8")
        blank = {}
        apply_cell_meter(blank, {"ledger_dir": str(empty), "cell_id": "empty"})
        self.assertEqual(blank["requests_count"], 0)
        self.assertNotIn("requests_error", blank)
        missing = {}
        apply_cell_meter(missing, {"ledger_dir": str(empty), "cell_id": "absent"})
        self.assertNotIn("requests_count", missing)

    def test_vertex_proxy_records_status_on_success_and_error(self):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _StatusUpstream)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.shutdown)
        host, port = httpd.server_address
        ledger = Path(tempfile.mkdtemp())
        proxy = start_proxy(
            "proj", token="tok", upstream=f"http://{host}:{port}", ledger_dir=ledger,
        )
        self.addCleanup(proxy.close)
        body = json.dumps({
            "model": "claude-opus-5-5",
            "max_tokens": 8,
            "messages": [{"role": "user", "content": "hello"}],
        }).encode()
        status, _payload = _post(proxy.base_url + "/c/cell-1/v1/messages", body)
        self.assertEqual(status, 200)
        bad = json.dumps({
            "model": "claude-opus-5-5",
            "max_tokens": 8,
            "messages": [{"role": "user", "content": "bad-request"}],
        }).encode()
        status, payload = _post(proxy.base_url + "/c/cell-1/v1/messages", bad)
        self.assertEqual(status, 400)
        self.assertGreater(len(payload), 500)
        rows = [
            json.loads(line)
            for line in (ledger / "cell-1.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual([row["status"] for row in rows], [200, 400])
        self.assertIn("usage", rows[0])
        self.assertNotIn("usage", rows[1])
        self.assertEqual(len(rows[1]["error"]), 500)
        self.assertIn("bad request", rows[1]["error"])

    def test_vertex_proxy_records_a_url_error(self):
        ledger = Path(tempfile.mkdtemp())
        proxy = start_proxy(
            "proj", token="tok", upstream="http://127.0.0.1:1", ledger_dir=ledger,
        )
        self.addCleanup(proxy.close)
        body = json.dumps({
            "model": "claude-opus-5-5",
            "max_tokens": 8,
            "messages": [{"role": "user", "content": "hello"}],
        }).encode()
        status, _payload = _post(proxy.base_url + "/c/cell-9/v1/messages", body)
        self.assertEqual(status, 502)
        row = json.loads((ledger / "cell-9.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(row["status"], 502)
        self.assertIn("error", row)
        self.assertNotIn("usage", row)


class OmpBuildTests(unittest.TestCase):
    def test_bun_requirement_falls_back_to_engines(self):
        root = Path(tempfile.mkdtemp())
        (root / "package.json").write_text(json.dumps({
            "engines": {"bun": ">=1.3.7"},
        }), encoding="utf-8")
        self.assertEqual(bun_requirement(root), ">=1.3.7")
        (root / "package.json").write_text(json.dumps({
            "packageManager": "bun@1.2.3",
            "engines": {"bun": ">=1.3.7"},
        }), encoding="utf-8")
        self.assertEqual(bun_requirement(root), "1.2.3")
        (root / ".bun-version").write_text("v1.0.0\n", encoding="utf-8")
        self.assertEqual(bun_requirement(root), "1.0.0")

    def _repo(self) -> Path:
        root = Path(tempfile.mkdtemp())
        env = os.environ.copy()
        env.update({
            "GIT_AUTHOR_NAME": "OpenBench",
            "GIT_AUTHOR_EMAIL": "openbench@example.com",
            "GIT_COMMITTER_NAME": "OpenBench",
            "GIT_COMMITTER_EMAIL": "openbench@example.com",
        })

        def git(*args):
            subprocess.run(
                ["git", *args], cwd=root, check=True, env=env,
                capture_output=True, text=True,
            )

        git("init")
        (root / "crates").mkdir()
        (root / "crates" / "lib.rs").write_text("fn main() {}\n", encoding="utf-8")
        natives = root / "packages" / "natives"
        natives.mkdir(parents=True)
        (natives / "package.json").write_text(
            json.dumps({"version": "1.2.3"}), encoding="utf-8",
        )
        (root / "package.json").write_text(
            json.dumps({"scripts": {"build:native": "echo native"}}),
            encoding="utf-8",
        )
        git("add", ".")
        git("commit", "-m", "init")
        git("tag", "v1.2.3")
        return root

    def test_published_natives_when_crates_match_the_tag(self):
        root = self._repo()
        seen = {}

        def opener(url):
            seen["url"] = url
            return b"node-bytes"

        self.assertEqual(prepare_natives(root, opener=opener), "published")
        name = native_asset_name()
        self.assertEqual(
            seen["url"],
            f"https://github.com/can1357/oh-my-pi/releases/download/v1.2.3/{name}",
        )
        native = root / "packages" / "natives" / "native"
        self.assertEqual((native / name).read_bytes(), b"node-bytes")
        self.assertEqual((native / "pi_natives.node").read_bytes(), b"node-bytes")

    def test_cargo_when_crates_change_and_skip_without_build_native(self):
        root = self._repo()
        (root / "crates" / "lib.rs").write_text("fn changed() {}\n", encoding="utf-8")
        env = os.environ.copy()
        env.update({
            "GIT_AUTHOR_NAME": "OpenBench",
            "GIT_AUTHOR_EMAIL": "openbench@example.com",
            "GIT_COMMITTER_NAME": "OpenBench",
            "GIT_COMMITTER_EMAIL": "openbench@example.com",
        })
        subprocess.run(["git", "add", "."], cwd=root, check=True, env=env, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "crates"], cwd=root, check=True, env=env,
            capture_output=True, text=True,
        )
        called = {}

        def opener(url):
            called["url"] = url
            return b"nope"

        self.assertEqual(
            prepare_natives(root, opener=opener, npm_fetch=lambda spec: {}),
            "cargo",
        )
        self.assertEqual(called, {})
        (root / "package.json").write_text(json.dumps({"scripts": {}}), encoding="utf-8")
        self.assertEqual(
            prepare_natives(root, opener=opener, npm_fetch=lambda spec: {}),
            "skip",
        )

    def test_empty_native_asset_is_a_build_error(self):
        root = self._repo()

        def opener(url):
            return b""

        with self.assertRaises(BuildError):
            prepare_natives(root, opener=opener, npm_fetch=lambda spec: {})

    def test_bun_defaults_when_the_commit_has_no_pin(self):
        root = Path(tempfile.mkdtemp())
        (root / "package.json").write_text(json.dumps({"name": "omp"}), encoding="utf-8")
        self.assertEqual(bun_version_for_build(root), PINNED_BUN)
        self.assertEqual(PINNED_BUN, "1.4.3")

    def test_renamed_release_asset_and_npm_fallback_are_mocked(self):
        root = self._repo()
        version = "1.2.3"
        legacy, modern, baseline = native_asset_candidates()
        self.assertTrue(modern.endswith("-modern.node"))
        self.assertTrue(baseline.endswith("-baseline.node"))
        generic, platform_pkg = npm_native_specs(version)
        self.assertEqual(generic, f"@oh-my-pi/pi-natives@{version}")
        self.assertIn("@oh-my-pi/pi-natives-", platform_pkg)
        self.assertTrue(platform_pkg.endswith(f"@{version}"))

        def opener(url):
            if url.endswith("/" + modern):
                return b"modern-bytes"
            if url.endswith("/" + baseline):
                return b"baseline-bytes"
            raise OSError(url)

        self.assertEqual(prepare_natives(root, opener=opener), "published")
        native = root / "packages" / "natives" / "native"
        self.assertEqual((native / modern).read_bytes(), b"modern-bytes")
        self.assertEqual((native / baseline).read_bytes(), b"baseline-bytes")
        self.assertEqual((native / "pi_natives.node").read_bytes(), b"modern-bytes")

        moved = self._repo()
        (moved / "crates" / "lib.rs").write_text("fn changed() {}\n", encoding="utf-8")
        env = os.environ.copy()
        env.update({
            "GIT_AUTHOR_NAME": "OpenBench",
            "GIT_AUTHOR_EMAIL": "openbench@example.com",
            "GIT_COMMITTER_NAME": "OpenBench",
            "GIT_COMMITTER_EMAIL": "openbench@example.com",
        })
        subprocess.run(["git", "add", "."], cwd=moved, check=True, env=env, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "crates"], cwd=moved, check=True, env=env,
            capture_output=True, text=True,
        )
        asked = []

        def npm_fetch(spec):
            asked.append(spec)
            if spec == platform_pkg:
                # The platform package ships linux-x64-{modern,baseline}.node,
                # not the older pi_natives.<name> release asset.
                return {
                    modern.split(".", 1)[1]: b"npm-modern",
                    baseline.split(".", 1)[1]: b"npm-baseline",
                }
            return {}

        def missing(url):
            raise OSError(url)

        self.assertEqual(
            prepare_natives(moved, opener=missing, npm_fetch=npm_fetch),
            "published",
        )
        self.assertEqual(asked, [generic, platform_pkg])
        installed = moved / "packages" / "natives" / "native"
        self.assertEqual(
            (installed / modern.split(".", 1)[1]).read_bytes(), b"npm-modern",
        )
        self.assertEqual((installed / "pi_natives.node").read_bytes(), b"npm-modern")

    def _cargo_scripts(self, root: Path) -> None:
        (root / "package.json").write_text(json.dumps({
            "scripts": {
                "build:native": "cargo build -p pi-natives",
                "build": "bun run build:ws",
            },
        }), encoding="utf-8")
        pkg_path = root / "packages" / "natives" / "package.json"
        package = json.loads(pkg_path.read_text(encoding="utf-8"))
        package["scripts"] = {"build": "cargo build -p pi-natives"}
        pkg_path.write_text(json.dumps(package), encoding="utf-8")
        entry = root / "packages" / "coding-agent" / "dist" / "cli.js"
        entry.parent.mkdir(parents=True)
        entry.write_text("cli\n", encoding="utf-8")

    def _tarball(self, cwd, members: dict[str, bytes]) -> None:
        path = Path(cwd) / "pkg.tgz"
        with tarfile.open(path, "w:gz") as archive:
            for name, body in members.items():
                info = tarfile.TarInfo(f"package/{name}")
                info.size = len(body)
                archive.addfile(info, io.BytesIO(body))

    def _plan_from_mocked_npm(self, root: Path, members_for):
        asked = []
        writes = []
        real_write = Path.write_bytes
        real_run = subprocess.run

        def spy_write(path, data):
            writes.append((path.name, bytes(data)))
            return real_write(path, data)

        def fake_run(cmd, cwd=None, **kwargs):
            if isinstance(cmd, list) and cmd[:2] == ["npm", "pack"]:
                spec = cmd[2]
                asked.append(spec)
                self._tarball(cwd, members_for(spec))
                return subprocess.CompletedProcess(cmd, 0, stdout="pkg.tgz\n", stderr="")
            return real_run(cmd, cwd=cwd, **kwargs)

        def opener(url):
            raise OSError(url)

        with patch("thesis.ab.build_omp.subprocess.run", side_effect=fake_run), \
                patch.object(Path, "write_bytes", spy_write):
            mode, cargo_bin = plan_natives(root, opener=opener)
        return mode, cargo_bin, asked, writes

    def _assert_compile_skips_cargo(self, root: Path, mode: str, cargo_bin) -> None:
        calls = []

        def runner(cmd, cwd, env):
            calls.append(list(cmd))
            joined = " ".join(cmd)
            if "cargo" in joined or "build:native" in joined:
                raise AssertionError(joined)

        compile_tree(root, Path("/tmp/bun-bin/bun"), cargo_bin, natives=mode, runner=runner)
        self.assertEqual(calls, [["bun", "install"], ["bun", "run", "build"]])
        root_scripts = json.loads((root / "package.json").read_text(encoding="utf-8"))["scripts"]
        native_scripts = json.loads(
            (root / "packages" / "natives" / "package.json").read_text(encoding="utf-8"),
        )["scripts"]
        self.assertEqual(root_scripts["build:native"], "true")
        self.assertEqual(native_scripts["build"], "true")

    def test_generic_npm_package_installs_prebuilt_and_skips_cargo(self):
        root = self._repo()
        self._cargo_scripts(root)
        version = "1.2.3"
        generic, platform_pkg = npm_native_specs(version)
        token = platform_pkg.rsplit("@", 1)[0].split("pi-natives-", 1)[1]
        modern = f"pi_natives.{token}-modern.node"
        baseline = f"pi_natives.{token}-baseline.node"

        def members_for(spec):
            if spec == generic:
                return {modern: b"generic-modern", baseline: b"generic-baseline"}
            return {}

        mode, cargo_bin, asked, writes = self._plan_from_mocked_npm(root, members_for)
        self.assertEqual(mode, "published")
        self.assertIsNone(cargo_bin)
        self.assertEqual(asked, [generic, platform_pkg])
        self.assertIn((modern, b"generic-modern"), writes)
        self.assertIn(("pi_natives.node", b"generic-modern"), writes)
        native = root / "packages" / "natives" / "native"
        self.assertEqual((native / modern).read_bytes(), b"generic-modern")
        self.assertEqual((native / "pi_natives.node").read_bytes(), b"generic-modern")
        self._assert_compile_skips_cargo(root, mode, cargo_bin)

    def test_platform_npm_package_installs_linux_variants_and_skips_cargo(self):
        root = self._repo()
        self._cargo_scripts(root)
        version = "1.2.3"
        generic, platform_pkg = npm_native_specs(version)
        token = platform_pkg.rsplit("@", 1)[0].split("pi-natives-", 1)[1]
        modern = f"{token}-modern.node"
        baseline = f"{token}-baseline.node"

        def members_for(spec):
            if spec == platform_pkg:
                return {modern: b"plat-modern", baseline: b"plat-baseline"}
            return {}

        mode, cargo_bin, asked, writes = self._plan_from_mocked_npm(root, members_for)
        self.assertEqual(mode, "published")
        self.assertIsNone(cargo_bin)
        self.assertEqual(asked, [generic, platform_pkg])
        self.assertIn((modern, b"plat-modern"), writes)
        self.assertIn((baseline, b"plat-baseline"), writes)
        self.assertIn(("pi_natives.node", b"plat-modern"), writes)
        native = root / "packages" / "natives" / "native"
        self.assertEqual((native / modern).read_bytes(), b"plat-modern")
        self.assertEqual((native / baseline).read_bytes(), b"plat-baseline")
        self.assertEqual((native / "pi_natives.node").read_bytes(), b"plat-modern")
        self._assert_compile_skips_cargo(root, mode, cargo_bin)

    def test_source_build_names_the_toolchain_and_does_not_run_cargo(self):
        root = self._repo()
        (root / "rust-toolchain.toml").write_text(
            '[toolchain]\nchannel = "nightly-2026-03-27"\n',
            encoding="utf-8",
        )

        def installer(channel):
            raise BuildError(f"rustup toolchain install {channel} failed")

        def opener(url):
            raise OSError(url)

        with patch("thesis.ab.build_omp._run", side_effect=AssertionError("cargo invoked")):
            with self.assertRaises(BuildError) as caught:
                plan_natives(
                    root, opener=opener, npm_fetch=lambda spec: {},
                    host_rustc="1.85.1", active="1.85.1", installer=installer,
                )
        message = str(caught.exception)
        self.assertIn("pi-natives source build needs rust toolchain nightly-2026-03-27", message)
        self.assertIn("host rustc is 1.85.1", message)

    def test_source_build_runs_only_when_the_toolchain_is_available(self):
        root = self._repo()
        self._cargo_scripts(root)
        (root / "rust-toolchain.toml").write_text(
            '[toolchain]\nchannel = "nightly-2026-03-27"\n',
            encoding="utf-8",
        )
        cargo = Path("/opt/rust-nightly/bin")

        def installer(channel):
            self.assertEqual(channel, "nightly-2026-03-27")
            return cargo

        def opener(url):
            raise OSError(url)

        mode, cargo_bin = plan_natives(
            root, opener=opener, npm_fetch=lambda spec: {},
            host_rustc="1.85.1", active="1.85.1", installer=installer,
        )
        self.assertEqual(mode, "cargo")
        self.assertEqual(cargo_bin, cargo)
        calls = []

        def runner(cmd, cwd, env):
            calls.append((list(cmd), env["PATH"]))

        compile_tree(root, Path("/tmp/bun-bin/bun"), cargo_bin, natives=mode, runner=runner)
        commands = [cmd for cmd, _path in calls]
        self.assertIn(["bun", "run", "build:native"], commands)
        self.assertTrue(calls[0][1].startswith(str(cargo) + os.pathsep))

        skipped = []

        def refuse(channel):
            skipped.append(channel)
            raise AssertionError(channel)

        matched, matched_bin = plan_natives(
            root, opener=opener, npm_fetch=lambda spec: {},
            host_rustc="1.91.0-nightly",
            active="nightly-2026-03-27-x86_64-unknown-linux-gnu",
            installer=refuse,
        )
        self.assertEqual(matched, "cargo")
        self.assertIsNone(matched_bin)
        self.assertEqual(skipped, [])

    def test_unreleased_natives_changelog_uses_the_next_published_version(self):
        published = ["17.3.7", "17.3.8", "17.4.0", "17.5.0"]
        self.assertEqual(next_published_natives("17.3.8", published), "17.4.0")
        self.assertIsNone(next_published_natives("17.5.0", published))
        unreleased = textwrap.dedent("""\
            # @oh-my-pi/pi-natives

            ## [Unreleased]

            - ClaudeV5 encoding

            ## [17.3.8]

            - previous
            """)
        empty = textwrap.dedent("""\
            # @oh-my-pi/pi-natives

            ## [Unreleased]

            ## [17.3.8]

            - previous
            """)

        def select(changelog: str) -> tuple[Path, list[str], str, int]:
            root = Path(tempfile.mkdtemp())
            subprocess.run(
                ["git", "init"], cwd=root, check=True, capture_output=True,
            )
            natives = root / "packages" / "natives"
            natives.mkdir(parents=True)
            (natives / "package.json").write_text(
                json.dumps({"version": "17.3.8"}), encoding="utf-8",
            )
            (natives / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
            (root / "package.json").write_text(
                json.dumps({"scripts": {"build:native": "echo native"}}),
                encoding="utf-8",
            )
            asked: list[str] = []

            def npm_fetch(spec: str) -> dict:
                asked.append(spec)
                return {}

            def opener(url: str) -> bytes:
                raise AssertionError(url)

            log = io.StringIO()
            with patch(
                "thesis.ab.build_omp._npm_published_versions", return_value=published,
            ) as view, contextlib.redirect_stderr(log):
                prepare_natives(root, opener=opener, npm_fetch=npm_fetch)
            return root, asked, log.getvalue(), view.call_count

        root, asked, log, calls = select(unreleased)
        self.assertTrue(has_unreleased_native_changes(root))
        self.assertEqual(calls, 1)
        self.assertTrue(asked)
        self.assertTrue(all(spec.endswith("@17.4.0") for spec in asked))
        self.assertIn("pi-natives 17.4.0", log)

        root, asked, log, calls = select(empty)
        self.assertFalse(has_unreleased_native_changes(root))
        self.assertEqual(calls, 0)
        self.assertTrue(asked)
        self.assertTrue(all(spec.endswith("@17.3.8") for spec in asked))
        self.assertNotIn("17.4.0", log)
        self.assertIn("pi-natives 17.3.8", log)


if __name__ == "__main__":
    unittest.main()
