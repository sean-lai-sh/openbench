"""Recording proxy for the reflection loop's Vertex models (SEA-105).

OpenCode talks to ``http://127.0.0.1:<port>/m/<model key>/...`` (the
provider ``baseURL`` from ``vertex_models.opencode_config``). For each POST
the proxy:

1. resolves the route to one registered model (``vertex_models.resolve``;
   unknown keys get 404) and checks the model the client named is that
   model (400 ``model_mismatch`` otherwise, so nothing silently falls back);
2. sets the model's thinking explicitly (``VertexModel.thinking``) and fixes
   the body for Vertex (Anthropic: no ``model``, ``anthropic_version``;
   OpenAI-compatible: publisher/model; streaming usage on);
3. forwards to the model's fixed Vertex URL with an ADC bearer token (the
   client's placeholder key is dropped), and streams the response back
   unchanged;
4. appends one ``openbench.reflection.wire/v1`` record (request as sent,
   model served, response usage, cost) to the wire JSONL.

Calls without tools are tagged ``call_role: "side"`` (OpenCode's title and
summary calls); every agent step carries tools. stdlib only.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from obench.reflection import vertex_models as vm
from obench.reflection.patches import PatchError, apply_patch, validate_patch
from obench.reflection.trace import WIRE_SCHEMA, TraceError, usage_from_response

ANTHROPIC_VERSION = "vertex-2023-10-16"
_FORWARD_HEADERS = ("anthropic-beta",)
_ANTHROPIC_THINKING_CONFLICTS = ("temperature", "top_k", "top_p")


def prepare_request(model: vm.VertexModel, client_path: str, body: dict) -> tuple[dict, bool, dict]:
    """``(body to send, stream?, enforcement record)``. Raises ValueError with
    a ``model_mismatch:`` prefix if the client named another model."""
    sent = json.loads(json.dumps(body))
    record: dict = {"setting": model.thinking}
    if model.wire == "anthropic":
        asked = sent.pop("model", None)
        if asked not in model.client_ids:
            raise ValueError(f"model_mismatch: route {model.key} got model {asked!r}")
        stream = bool(sent.get("stream"))
        sent.pop("stream", None) if not stream else None
        sent["anthropic_version"] = ANTHROPIC_VERSION
        record["client"] = body.get("thinking")
        sent["thinking"] = dict(model.thinking)
        removed = [k for k in _ANTHROPIC_THINKING_CONFLICTS if sent.pop(k, None) is not None]
        if removed:
            record["removed"] = removed
        return sent, stream, record
    if model.wire == "openai_chat":
        asked = sent.get("model")
        if asked not in model.client_ids:
            raise ValueError(f"model_mismatch: route {model.key} got model {asked!r}")
        sent["model"] = vm.OPENAI_BODY_MODEL[model.key]
        stream = bool(sent.get("stream"))
        if stream:
            sent["stream_options"] = dict(sent.get("stream_options") or {}, include_usage=True)
        record["client"] = {k: body.get(k) for k in ("reasoning_effort", "reasoning") if k in body} or None
        sent.pop("reasoning", None)
        sent.update(model.thinking)
        return sent, stream, record
    # gemini: the model is in the client's path, .../models/<id>:<verb>
    tail = client_path.rsplit("/models/", 1)[-1]
    asked, _, verb = tail.partition(":")
    if asked not in model.client_ids:
        raise ValueError(f"model_mismatch: route {model.key} got model {asked!r}")
    stream = verb.startswith("streamGenerateContent")
    config = dict(sent.get("generationConfig") or {})
    record["client"] = config.get("thinkingConfig")
    config["thinkingConfig"] = dict(model.thinking)
    sent["generationConfig"] = config
    return sent, stream, record


def _sse_payloads(raw: bytes):
    for block in raw.decode("utf-8", "replace").replace("\r\n", "\n").split("\n\n"):
        data = "\n".join(line[5:].strip() for line in block.split("\n") if line.startswith("data:"))
        if data and data != "[DONE]":
            try:
                yield json.loads(data)
            except json.JSONDecodeError:
                continue


def parse_response(model: vm.VertexModel, raw: bytes, stream: bool) -> tuple[dict | None, str | None]:
    """``(response usage object, served model)`` from a full response body.
    Usage is None when the response carried none."""
    if not stream:
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None, None
        if model.wire == "gemini":
            doc = doc[-1] if isinstance(doc, list) and doc else doc
            return (doc.get("usageMetadata"), doc.get("modelVersion")) if isinstance(doc, dict) else (None, None)
        return (doc.get("usage"), doc.get("model")) if isinstance(doc, dict) else (None, None)
    usage, served = None, None
    for event in _sse_payloads(raw):
        if model.wire == "anthropic":
            if event.get("type") == "message_start":
                message = event.get("message") or {}
                usage, served = dict(message.get("usage") or {}), message.get("model") or served
            elif event.get("type") == "message_delta" and isinstance(event.get("usage"), dict):
                usage = {**(usage or {}), **event["usage"]}
        elif model.wire == "gemini":
            if isinstance(event.get("usageMetadata"), dict):
                usage = event["usageMetadata"]
            served = event.get("modelVersion") or served
        else:
            if isinstance(event.get("usage"), dict):
                usage = event["usage"]
            served = event.get("model") or served
    return usage, served


class WireProxy:
    """One proxy per run. ``base_url`` goes into the OpenCode config;
    ``wire_path`` collects the wire records."""

    def __init__(self, project: str, wire_path: Path, token: Callable[[], str], *,
                 host: str = "127.0.0.1", port: int = 0, upstream_host: str | None = None,
                 opener=urllib.request.urlopen, patch: dict | None = None, patch_id: str | None = None):
        if (patch is None) != (patch_id is None):
            raise ValueError("patch and patch_id go together")
        if patch is not None:
            reasons = validate_patch(patch)
            if reasons:
                raise PatchError("; ".join(reasons))
        self.patch, self.patch_id = patch, patch_id
        self.project, self.wire_path, self.token = project, Path(wire_path), token
        self.upstream_host, self.opener = upstream_host, opener
        self._lock, self._index = threading.Lock(), 0
        self.wire_path.parent.mkdir(parents=True, exist_ok=True)
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt, *args):
                return

            def do_POST(self):  # noqa: N802
                proxy.handle(self)

        self.server = ThreadingHTTPServer((host, port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _url(self, model: vm.VertexModel, stream: bool) -> str:
        url = model.upstream_url(self.project, stream)
        if self.upstream_host:  # tests point the proxy at a fake Vertex
            url = self.upstream_host.rstrip("/") + url[len(vm.VERTEX_HOST):]
        return url

    def _reply(self, handler, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)

    def handle(self, handler) -> None:
        path = urllib.parse.urlsplit(handler.path).path
        parts = [p for p in path.split("/") if p]
        length = int(handler.headers.get("Content-Length") or 0)
        raw = handler.rfile.read(length) if length else b""
        if len(parts) < 2 or parts[0] != "m":
            return self._reply(handler, 404, {"error": "unknown route; expected /m/<model>/..."})
        try:
            model = vm.resolve(parts[1])
        except vm.UnknownModel as exc:
            return self._reply(handler, 404, {"error": str(exc)})
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
            sent, stream, enforced = prepare_request(model, path, body)
            patch_log = None
            if self.patch is not None:  # ideation alternative: prompt / tool-metadata ops only
                sent, patch_log = apply_patch(model.wire, sent, self.patch)
                enforced = dict(enforced, patch_id=self.patch_id, patch_log=patch_log)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._reply(handler, 400, {"error": "request body is not JSON"})
        except ValueError as exc:
            return self._reply(handler, 400, {"error": str(exc)})
        with self._lock:
            self._index += 1
            index = self._index
        started = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.token()}"}
        for name in _FORWARD_HEADERS:
            if handler.headers.get(name):
                headers[name] = handler.headers[name]
        request = urllib.request.Request(self._url(model, stream), data=json.dumps(sent).encode("utf-8"),
                                         headers=headers, method="POST")
        status, chunks, content_type = None, [], "application/json"
        try:
            response = self.opener(request, timeout=600)
        except urllib.error.HTTPError as exc:
            response = exc
        except OSError as exc:
            self._record(index, started, model, sent, enforced, None, None, None, str(exc))
            return self._reply(handler, 502, {"error": f"upstream unreachable: {exc}"})
        with response:
            status = getattr(response, "status", None) or response.getcode()
            content_type = response.headers.get("Content-Type", content_type)
            handler.send_response(status)
            handler.send_header("Content-Type", content_type)
            handler.send_header("Transfer-Encoding", "chunked")
            handler.end_headers()
            while True:
                piece = response.read1(65536) if hasattr(response, "read1") else response.read(65536)
                if not piece:
                    break
                chunks.append(piece)
                handler.wfile.write(f"{len(piece):X}\r\n".encode() + piece + b"\r\n")
                handler.wfile.flush()
            # Record before the final chunk, so the record exists once the client has the full reply.
            usage, served = parse_response(model, b"".join(chunks), stream) if status == 200 else (None, None)
            self._record(index, started, model, sent, enforced, usage, served, status, None)
            handler.wfile.write(b"0\r\n\r\n")

    def _record(self, index, started, model, sent, enforced, usage, served, status, error) -> None:
        tools = sent.get("tools")
        record = {
            "schema": WIRE_SCHEMA, "call_index": index, "ts": started, "provider_wire": model.wire,
            "call_role": "main" if isinstance(tools, list) and tools else "side",
            "requested_model": model.vertex_id, "upstream_model": served,
            "request": sent, "response_usage": usage, "status": status,
            "route": model.key, "thinking_enforced": enforced, "cost_usd": None, "cost_basis": None,
        }
        if self.patch_id is not None:
            record["patch_id"] = self.patch_id
        if error:
            record["error"] = error
        if usage is not None:
            try:
                detail = vm.cost_detail(model, usage_from_response(model.wire, usage, index))
                record["cost_usd"], record["cost_basis"] = detail["usd"], detail["basis"]
            except TraceError as exc:
                record["usage_error"] = exc.code
        with self._lock, self.wire_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
