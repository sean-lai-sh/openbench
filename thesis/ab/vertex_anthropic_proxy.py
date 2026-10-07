from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from obench.proxy import extract_usage

ANTHROPIC_VERSION = "vertex-2023-10-16"
MODEL_ID = "claude-opus-5-5"
LOCATION = "global"
_FORWARDED = ("anthropic-beta", "anthropic-version")
_LEDGER_LOCK = threading.Lock()
_DISCONNECT = (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, TimeoutError)


class ProxyError(RuntimeError):
    pass


def vertex_path(project: str, model: str, kind: str, location: str = LOCATION) -> str:
    suffix = {
        "raw": ":rawPredict",
        "stream": ":streamRawPredict",
        "count": ":countTokens",
    }[kind]
    return (
        f"/v1/projects/{project}/locations/{location}"
        f"/publishers/anthropic/models/{model}{suffix}"
    )


def translate_body(path: str, body: bytes) -> tuple[str, bytes]:
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProxyError(f"request body is not JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ProxyError("request body must be an object")
    data.pop("model", None)
    data["anthropic_version"] = ANTHROPIC_VERSION
    route = path.split("?", 1)[0].rstrip("/")
    if route.endswith("/count_tokens") or route.endswith("/countTokens"):
        kind = "count"
    elif data.get("stream") is True:
        kind = "stream"
    else:
        kind = "raw"
        data.pop("stream", None)
    return kind, json.dumps(data).encode("utf-8")


def split_cell_path(path: str) -> tuple[str | None, str]:
    query = ""
    route = path
    if "?" in path:
        route, query = path.split("?", 1)
        query = "?" + query
    parts = [part for part in route.split("/") if part]
    if len(parts) >= 2 and parts[0] == "c" and parts[1]:
        return parts[1], "/" + "/".join(parts[2:]) + query
    return None, path


def cell_proxy_base(base_url: str, cell_id: str) -> str:
    base = base_url.rstrip("/")
    tail = ""
    if base.endswith("/v1"):
        base = base[:-3]
        tail = "/v1"
    return f"{base}/c/{cell_id}{tail}"


_TOKEN_MARKERS = frozenset({
    "input_tokens", "output_tokens", "prompt_tokens", "completion_tokens",
    "total_tokens", "cache_read_input_tokens", "cache_creation_input_tokens",
    "totalTokens",
})
_LEDGER_USAGE_KEYS = frozenset({
    "input_tokens", "output_tokens",
    "cache_read_input_tokens", "cache_creation_input_tokens", "cache_creation",
    "cache_write_tokens", "cached_input_tokens",
    "prompt_tokens", "completion_tokens", "total_tokens",
    "reasoning_output_tokens", "reasoning_tokens",
    "input_tokens_details", "output_tokens_details",
    "prompt_tokens_details", "completion_tokens_details",
    "prompt_cache_hit_tokens", "prompt_cache_miss_tokens", "prompt_cache_write_tokens",
    "cacheRead", "cacheWrite", "reasoning", "totalTokens",
})
_LEDGER_TIMING_KEYS = frozenset({
    "started_at", "ended_at", "duration_ms", "latency_ms",
    "time_to_first_token_ms", "elapsed_ms", "ttft_ms",
})


def _has_token_marker(obj: dict) -> bool:
    return any(key in obj for key in _TOKEN_MARKERS)


def _is_tool_call(obj: dict) -> bool:
    if obj.get("type") in {"tool_use", "tool_result", "server_tool_use"}:
        return True
    return isinstance(obj.get("input"), dict) and "name" in obj


def _token_usage(obj) -> dict | None:
    """Last real token-usage object, skipping tool-call blocks.

    ``extract_usage`` treats a ``tool_use`` block as usage because the block
    has an ``input`` key. That copies the tool name and arguments into the
    ledger. A nested ``usage`` object with token fields wins instead.
    """
    found = None

    def walk(node) -> None:
        nonlocal found
        if isinstance(node, dict):
            usage = node.get("usage")
            if isinstance(usage, dict) and _has_token_marker(usage):
                found = usage
            elif _has_token_marker(node) and not _is_tool_call(node):
                found = node
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(obj)
    return found


def _select_usage(obj) -> dict | None:
    raw = extract_usage(obj)
    if not isinstance(raw, dict):
        return None
    token = _token_usage(obj)
    return token if token is not None else raw


def trim_ledger_usage(usage: dict) -> tuple[dict, dict]:
    """Keep token usage and timing. Drop tool-call fields.

    Numeric ``input`` / ``output`` stay (the pi token shape). A tool's
    ``input`` object does not. An empty usage dict is still a row so the
    request count matches the pre-trim ledger.
    """
    kept: dict = {}
    timing: dict = {}
    for key, value in usage.items():
        if key in ("input", "output") and isinstance(value, (int, float)) and not isinstance(value, bool):
            kept[key] = value
        elif key in _LEDGER_TIMING_KEYS:
            timing[key] = value
        elif key in _LEDGER_USAGE_KEYS:
            kept[key] = value
    return kept, timing


def _usage_from_block(block: bytes) -> dict | None:
    data_lines = []
    for line in block.splitlines():
        if line.startswith(b"data:"):
            data_lines.append(line[5:].lstrip())
    if not data_lines:
        return None
    data = b"\n".join(data_lines).strip()
    if not data or data == b"[DONE]":
        return None
    try:
        obj = json.loads(data)
    except json.JSONDecodeError:
        return None
    return _select_usage(obj)


def drain_sse(buf: bytes) -> tuple[bytes, list[dict]]:
    found = []
    while True:
        sep = None
        for marker in (b"\r\n\r\n", b"\n\n", b"\r\r"):
            index = buf.find(marker)
            if index != -1 and (sep is None or index < sep[0]):
                sep = (index, marker)
        if sep is None:
            break
        index, marker = sep
        usage = _usage_from_block(buf[:index])
        buf = buf[index + len(marker):]
        if usage:
            found.append(usage)
    return buf, found


def merge_message_usage(parts: list[dict]) -> dict | None:
    merged: dict = {}
    for part in parts:
        if not isinstance(part, dict):
            continue
        for key, value in part.items():
            if value is None:
                continue
            merged[key] = value
    creation = merged.get("cache_creation")
    current = merged.get("cache_creation_input_tokens")
    if isinstance(creation, dict) and (isinstance(current, bool) or not isinstance(current, (int, float))):
        total = 0
        saw = False
        for value in creation.values():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            total += int(value)
            saw = True
        if saw:
            merged["cache_creation_input_tokens"] = total
    return merged or None


def parse_sse_usages(payload: bytes) -> dict | None:
    pending, parts = drain_sse(payload)
    if pending.strip():
        extra = _usage_from_block(pending)
        if extra:
            parts.append(extra)
    return merge_message_usage(parts)


def _usage_from_json(payload: bytes) -> dict | None:
    try:
        obj = json.loads(payload.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return None
    usage = _select_usage(obj)
    return merge_message_usage([usage]) if isinstance(usage, dict) else None


def _cell_file_stem(cell_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", cell_id)


def cell_ledger_path(directory: Path, cell_id: str) -> Path:
    """Per-cell request ledger. One JSONL row per finished ``/c/<cell_id>/`` request.

    This is the file ``read_proxy_ledger`` and ``requests_*`` totals read.
    A post with no cell prefix is not written here.
    """
    return Path(directory) / f"{_cell_file_stem(cell_id)}.jsonl"


def cell_bytes_path(directory: Path, cell_id: str) -> Path:
    """In-flight byte total beside the cell ledger.

    The ledger row is written when a request finishes. A long stream updates
    this file on each chunk so the watchdog can see it before that row exists.
    """
    return cell_ledger_path(directory, cell_id).with_suffix(".bytes")


_BYTE_TOTALS: dict[str, int] = {}


def note_cell_bytes(directory: Path | None, cell_id: str | None, n: int) -> None:
    """Add ``n`` streamed bytes to the cell's on-disk counter.

    The proxy runs in the parent and the cell runs in a worker, so the file
    is the progress signal. ``n <= 0``, a missing ledger, or a missing cell
    id does nothing. The write is atomic so a reader never sees a partial
    integer.
    """
    if directory is None or not cell_id or n <= 0:
        return
    path = cell_bytes_path(Path(directory), cell_id)
    key = str(path)
    with _LEDGER_LOCK:
        if key not in _BYTE_TOTALS:
            try:
                _BYTE_TOTALS[key] = int(path.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                _BYTE_TOTALS[key] = 0
        total = _BYTE_TOTALS[key] + int(n)
        _BYTE_TOTALS[key] = total
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(str(total), encoding="utf-8")
        os.replace(tmp, path)


def _append_ledger(directory: Path, cell_id: str, usage: dict) -> None:
    path = cell_ledger_path(Path(directory), cell_id)
    kept, timing = trim_ledger_usage(usage)
    row = {"record_type": "request", "usage": kept}
    row.update(timing)
    line = json.dumps(row, sort_keys=True) + "\n"
    with _LEDGER_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())


class AdcToken:
    def __init__(self, path: Path | None = None, now=time.time):
        self.path = path
        self._now = now
        self._token = ""
        self._deadline = 0.0
        self._lock = threading.Lock()

    def __call__(self) -> str:
        with self._lock:
            if self._token and self._now() < self._deadline - 60:
                return self._token
            token, deadline = self._fetch()
            self._token = token
            self._deadline = deadline
            return token

    def _fetch(self) -> tuple[str, float]:
        info = json.loads(self._adc_path().read_text(encoding="utf-8"))
        kind = info.get("type")
        if kind == "authorized_user":
            return _refresh_authorized_user(info, self._now)
        if kind == "service_account":
            return _refresh_service_account(info, self._now)
        raise ProxyError(f"unsupported ADC type {kind!r}")

    def _adc_path(self) -> Path:
        if self.path is not None:
            return self.path
        env = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if env:
            return Path(env)
        return Path.home() / ".config" / "gcloud" / "application_default_credentials.json"


def _refresh_authorized_user(info: dict, now) -> tuple[str, float]:
    form = urllib.parse.urlencode({
        "client_id": info["client_id"],
        "client_secret": info["client_secret"],
        "refresh_token": info["refresh_token"],
        "grant_type": "refresh_token",
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.URLError as exc:
        raise ProxyError(f"ADC refresh failed: {exc}") from exc
    token = payload.get("access_token")
    if not token:
        raise ProxyError("ADC refresh returned no access_token")
    return token, now() + int(payload.get("expires_in") or 3600)


def _refresh_service_account(info: dict, now) -> tuple[str, float]:
    try:
        import google.auth
        import google.auth.transport.requests
    except ImportError as exc:
        raise ProxyError(
            "service-account ADC needs google-auth, or use an authorized_user ADC file"
        ) from exc
    credentials, _project = google.auth.load_credentials_from_dict(
        info, scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(google.auth.transport.requests.Request())
    expiry = credentials.expiry.timestamp() if credentials.expiry else now() + 3600
    return credentials.token, expiry


FAULTS = frozenset({"http-529", "http-429", "sse-server-error"})

# Mid-stream: one successful message_start, then the SSE error event from
# PR 5527. The first-chunk path in @ai-sdk/anthropic throws APICallError
# instead, so the event has to follow something the schema accepts.
_SSE_SERVER_ERROR = (
    "event: message_start\n"
    "data: {\"type\":\"message_start\",\"message\":{"
    "\"id\":\"msg_fault\",\"type\":\"message\",\"role\":\"assistant\","
    "\"content\":[],\"model\":\"claude-opus-5-5\",\"stop_reason\":null,"
    "\"stop_sequence\":null,\"usage\":{\"input_tokens\":1,\"output_tokens\":0}"
    "}}\n\n"
    "event: error\n"
    "data: {\"type\":\"error\",\"error\":{\"type\":\"server_error\",\"message\":\"no_kv_space\"}}\n\n"
).encode("utf-8")

_HTTP_529 = b'{"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}'
_HTTP_429 = b'{"type":"error","error":{"type":"rate_limit_error","message":"rate limited"}}'


def _message_route(route: str) -> bool:
    path = route.split("?", 1)[0].rstrip("/")
    return path.endswith("/messages")


def _system_text(data: dict) -> str:
    parts: list[str] = []
    system = data.get("system")
    if isinstance(system, str):
        parts.append(system)
    elif isinstance(system, list):
        for block in system:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
    messages = data.get("messages")
    if isinstance(messages, list):
        for message in messages:
            if not isinstance(message, dict) or message.get("role") != "system":
                continue
            content = message.get("content")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and isinstance(block.get("text"), str):
                        parts.append(block["text"])
    return "\n".join(parts)


def _is_main_loop_request(raw: bytes) -> bool:
    """True for the agent loop, false for title generation and other tiny calls.

    Title generation sends the title system prompt, a small max token budget,
    and no tools. The agent loop sends a tools array or a long system prompt.
    """
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    tools = data.get("tools")
    if isinstance(tools, list) and tools:
        return True
    text = _system_text(data).lower()
    if "title generator" in text or "never use tools" in text:
        return False
    max_tokens = data.get("max_tokens")
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, (int, float)):
        max_tokens = data.get("max_output_tokens")
    if (
        isinstance(max_tokens, (int, float))
        and not isinstance(max_tokens, bool)
        and max_tokens <= 64
    ):
        return False
    return len(text) >= 200


class Proxy:
    def __init__(self, httpd: ThreadingHTTPServer, thread: threading.Thread):
        self._httpd = httpd
        self._thread = thread
        self._faults: dict[str, dict] = {}
        self._fault_lock = threading.Lock()

    @property
    def base_url(self) -> str:
        host, port = self._httpd.server_address
        return f"http://{host}:{port}"

    def arm_fault(self, cell_id: str, kind: str, count: int = 1) -> None:
        """Return ``kind`` for the next ``count`` main-loop messages posts.

        Token-count posts, title generation, and other small no-tool requests
        are forwarded and do not consume the count. After ``count`` main-loop
        posts, later posts are forwarded.
        """
        if kind not in FAULTS:
            raise ProxyError(f"unknown fault {kind!r}")
        if not cell_id:
            raise ProxyError("fault injection needs a cell id")
        try:
            left = int(count)
        except (TypeError, ValueError) as exc:
            raise ProxyError(f"fault count must be an integer, got {count!r}") from exc
        if left < 1:
            raise ProxyError("fault count must be >= 1")
        with self._fault_lock:
            self._faults[cell_id] = {"kind": kind, "left": left}

    def take_fault(self, cell_id: str | None, route: str, body: bytes = b"") -> str | None:
        if not cell_id or not _message_route(route):
            return None
        if not _is_main_loop_request(body):
            return None
        with self._fault_lock:
            slot = self._faults.get(cell_id)
            if not slot:
                return None
            slot["left"] -= 1
            kind = slot["kind"]
            if slot["left"] <= 0:
                self._faults.pop(cell_id, None)
            return kind

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)


def start_proxy(project: str, *, model: str = MODEL_ID, location: str = LOCATION,
                token, upstream: str = "https://aiplatform.googleapis.com",
                ledger_dir: Path | None = None) -> Proxy:
    upstream = upstream.rstrip("/")
    ledger = Path(ledger_dir) if ledger_dir is not None else None
    holder: dict = {}

    class Server(ThreadingHTTPServer):
        def handle_error(self, request, client_address):
            exc = sys.exc_info()[1]
            if isinstance(exc, _DISCONNECT):
                return
            super().handle_error(request, client_address)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def handle(self):
            try:
                super().handle()
            except _DISCONNECT:
                self.close_connection = True

        def do_POST(self):  # noqa: N802 - stdlib name
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            cell, route = split_cell_path(self.path)
            if ledger is not None and cell and raw:
                note_cell_bytes(ledger, cell, len(raw))
            fault = holder["proxy"].take_fault(cell, route, raw)
            if fault:
                self._send_fault(fault)
                return
            try:
                kind, body = translate_body(route, raw)
                path = vertex_path(project, model, kind, location)
                bearer = token() if callable(token) else token
            except (ProxyError, OSError) as exc:
                payload = json.dumps({"error": str(exc)}).encode("utf-8")
                self._send(400, "application/json", payload)
                return
            headers = {
                "Authorization": f"Bearer {bearer}",
                "Content-Type": "application/json",
            }
            for name in _FORWARDED:
                value = self.headers.get(name)
                if value:
                    headers[name] = value
            self._forward(upstream + path, headers, body, cell if ledger is not None else None, kind)

        def _send(self, status: int, content_type: str, payload: bytes, extra: dict | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            for name, value in (extra or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(payload)

        def _send_fault(self, kind: str) -> None:
            if kind == "http-529":
                self._send(529, "application/json", _HTTP_529)
                return
            if kind == "http-429":
                self._send(429, "application/json", _HTTP_429, {"Retry-After": "1"})
                return
            self._send(200, "text/event-stream", _SSE_SERVER_ERROR)

        def _write_chunk(self, chunk: bytes) -> None:
            self.wfile.write(f"{len(chunk):X}\r\n".encode("ascii"))
            self.wfile.write(chunk)
            self.wfile.write(b"\r\n")
            self.wfile.flush()

        def _record(self, cell: str | None, usage: dict | None) -> None:
            # One row per messages POST on /c/<cell-id>/. A subagent or child
            # session that reused that base URL is included in the cell total.
            if ledger is None or not cell or not usage:
                return
            _append_ledger(ledger, cell, usage)

        def _forward(self, url: str, headers: dict, body: bytes, cell: str | None, kind: str) -> None:
            request = urllib.request.Request(url, data=body, headers=headers, method="POST")
            response = None
            raw = bytearray()
            parts: list[dict] = []
            pending = b""
            recorded = False

            def finish_usage() -> dict | None:
                nonlocal pending
                if kind == "stream":
                    if pending.strip():
                        extra = _usage_from_block(pending)
                        pending = b""
                        if extra:
                            parts.append(extra)
                    return merge_message_usage(parts)
                return _usage_from_json(bytes(raw))

            try:
                try:
                    response = urllib.request.urlopen(request, timeout=3600)
                except urllib.error.HTTPError as exc:
                    payload = exc.read()
                    note_cell_bytes(ledger, cell, len(payload))
                    content_type = exc.headers.get("Content-Type") or "application/json"
                    self._send(exc.code, content_type, payload)
                    return
                except urllib.error.URLError as exc:
                    payload = json.dumps({"error": str(exc)}).encode("utf-8")
                    self._send(502, "application/json", payload)
                    return
                status = response.status
                content_type = response.headers.get("Content-Type") or "application/json"
                if kind == "stream":
                    self.close_connection = True
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                if kind == "stream":
                    self.send_header("Connection", "close")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                while True:
                    chunk = response.read1(8192)
                    if not chunk:
                        break
                    # Count before the client write. A blocked consumer
                    # still moves the watchdog's byte file.
                    note_cell_bytes(ledger, cell, len(chunk))
                    raw.extend(chunk)
                    if kind == "stream":
                        pending += chunk
                        pending, found = drain_sse(pending)
                        parts.extend(found)
                    self._write_chunk(chunk)
                usage = finish_usage()
                if kind != "count":
                    self._record(cell, usage)
                    recorded = True
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except _DISCONNECT:
                self.close_connection = True
                if not recorded and kind != "count":
                    self._record(cell, finish_usage())
            finally:
                if response is not None:
                    response.close()

        def log_message(self, fmt, *args):
            return

    httpd = Server(("127.0.0.1", 0), Handler)
    proxy = Proxy(httpd, None)
    holder["proxy"] = proxy
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    proxy._thread = thread
    thread.start()
    return proxy


def start_from_env(ledger_dir: Path | None = None) -> Proxy:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCLOUD_PROJECT")
    if not project:
        raise ProxyError("GOOGLE_CLOUD_PROJECT is not set")
    return start_proxy(project, token=AdcToken(), ledger_dir=ledger_dir)
