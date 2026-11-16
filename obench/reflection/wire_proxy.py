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
from obench.reflection.gptoss_repair import repair as repair_text_tool_calls, to_sse
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
        record["client_effort"] = (sent.get("output_config") or {}).get("effort")
        sent["thinking"] = dict(model.thinking)
        if model.effort:  # explicit on every request; whatever the client asked for is recorded above
            sent["output_config"] = dict(sent.get("output_config") or {}, effort=model.effort)
        record["effort"] = (sent.get("output_config") or {}).get("effort")
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
                # message_start usage is a start snapshot (output_tokens 1, thinking 0). A thinking count is taken
                # only from the final message_delta; if that omits it, the count is unreported (None), not 0.
                usage.pop("thinking_tokens", None)
                if isinstance(usage.get("output_tokens_details"), dict):
                    details = {k: v for k, v in usage["output_tokens_details"].items() if k != "thinking_tokens"}
                    usage["output_tokens_details"] = details
                    if not details:
                        usage.pop("output_tokens_details")
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


def usage_events(model: vm.VertexModel, raw: bytes, stream: bool) -> list[dict] | None:
    """Anthropic streams: every usage object the response carried, in order (message_start, then each
    message_delta), so it is visible whether Vertex ever reports a thinking count and where."""
    if not stream or model.wire != "anthropic":
        return None
    out = []
    for event in _sse_payloads(raw):
        if event.get("type") == "message_start":
            out.append({"event": "message_start", "usage": (event.get("message") or {}).get("usage")})
        elif event.get("type") == "message_delta" and isinstance(event.get("usage"), dict):
            out.append({"event": "message_delta", "usage": event["usage"]})
    return out


def prompt_feedback(model: vm.VertexModel, raw: bytes, stream: bool) -> dict | None:
    """Gemini: the prompt itself was blocked (HTTP 200, ``promptFeedback.blockReason``, no candidates).
    Returns ``{blockReason, blockReasonMessage, safetyRatings}``, or None."""
    if model.wire != "gemini":
        return None
    if stream:
        events = list(_sse_payloads(raw))
    else:
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        events = doc if isinstance(doc, list) else [doc]
    events = [e for e in events if isinstance(e, dict)]
    if any(e.get("candidates") for e in events):
        return None
    for e in events:
        feedback = e.get("promptFeedback") or {}
        if feedback.get("blockReason"):
            return {"blockReason": feedback["blockReason"], "blockReasonMessage": feedback.get("blockReasonMessage"),
                    "safetyRatings": feedback.get("safetyRatings")}
    return None


def prompt_blocked(wire_records: list[dict]) -> dict | None:
    """The trial's prompt was blocked by the provider (Gemini ``promptFeedback.blockReason``): an outcome of its
    own, neither a task fail nor route_truncated / upstream_4xx / timeout. Records written before this field
    existed (2026-11-17) are recognised when every answered main call came back empty (no candidates: no finish
    reason, text, thinking or tool call); that is marked ``inferred``."""
    for w in sorted(wire_records, key=lambda w: w.get("call_index") or 0):
        if w.get("prompt_blocked"):
            return dict(w["prompt_blocked"], call_index=w.get("call_index"),
                        calls_blocked=sum(1 for x in wire_records if x.get("prompt_blocked")))
    main = [w for w in wire_records if w.get("call_role") != "side" and w.get("status") == 200]
    gemini = [w for w in main if w.get("provider_wire") == "gemini"]
    if gemini and len(gemini) == len(main) and all(
            not s.get("finish_reasons") and not s.get("text_chars") and not s.get("reasoning_chars")
            and not s.get("tool_calls") for s in (w.get("response_summary") or {} for w in gemini)):
        return {"blockReason": None, "inferred": True, "call_index": gemini[0].get("call_index"),
                "calls_blocked": len(gemini)}
    return None


STOP_REASONS = ("stop", "end_turn", "STOP")


def route_truncated(wire_records: list[dict]) -> dict | None:
    """The trial's last main call ended ``stop`` with no visible text and no tool call: the route cut the turn
    (an infrastructure failure, not a task failure). Returns what was seen, or None."""
    main = [w for w in wire_records if w.get("call_role") != "side" and w.get("status") == 200]
    if not main:
        return None
    last = max(main, key=lambda w: w.get("call_index") or 0)
    summary = last.get("response_summary") or {}
    finishes = summary.get("finish_reasons") or []
    no_call = not summary.get("tool_calls")
    empty = any(f in STOP_REASONS for f in finishes) and no_call and not summary.get("text_chars")
    # Harmony markup left in the text with no tool call (unrecovered, or an unknown recipient under "reject"):
    # the turn ended on a call OpenCode never saw.
    leaked = no_call and bool(summary.get("harmony_markers_in_text")) and any(
        f in (*STOP_REASONS, "tool_calls") for f in finishes)
    if empty or leaked:
        return {"call_index": last.get("call_index"), "finish_reasons": finishes, "kind": "empty" if empty else "harmony_leak",
                "reasoning_chars": summary.get("reasoning_chars"), "route_repair": last.get("route_repair")}
    return None


def upstream_4xx(wire_records: list[dict]) -> list[dict]:
    """Every model call (main or side) that came back 4xx."""
    return [{"call_index": w.get("call_index"), "status": w.get("status"), "call_role": w.get("call_role")}
            for w in wire_records if isinstance(w.get("status"), int) and 400 <= w["status"] < 500]


def classify_4xx(wire_records: list[dict]) -> dict:
    """Researcher ruling (2026-11-16): a 4xx is an infrastructure failure only if it ended or broke the trial,
    i.e. a main call came back 4xx and no main call after it succeeded. A 4xx that OpenCode retried and recovered
    from (a later main call returned 200), or one on a side call (titles), is not: it is counted by status code
    as a covariate (``retried``). Returns ``{"breaking": [calls], "retried": {"429": n, ...}}``."""
    order = sorted(wire_records, key=lambda w: w.get("call_index") or 0)
    last_ok = max((w.get("call_index") or 0 for w in order
                   if w.get("call_role") != "side" and w.get("status") == 200), default=-1)
    breaking, retried = [], {}
    for call in upstream_4xx(order):
        if call["call_role"] != "side" and (call["call_index"] or 0) > last_ok:
            breaking.append(call)
        else:
            retried[str(call["status"])] = retried.get(str(call["status"]), 0) + 1
    return {"breaking": breaking, "retried": retried}


def route_repair_counts(wire_records: list[dict]) -> dict:
    """How much of a trial rests on the gpt-oss route repair: main model calls answered (status 200), how many
    of them carried a structured tool call to OpenCode, and how many of those the proxy rebuilt from text."""
    main = [w for w in wire_records if w.get("call_role") != "side" and w.get("status") == 200]
    return {"model_calls": len(main),
            "tool_call_turns": sum(1 for w in main if (w.get("response_summary") or {}).get("tool_calls")),
            "route_repairs": sum(1 for w in main if (w.get("route_repair") or {}).get("applied")),
            "unknown_recipient_calls": sum(1 for w in main if (w.get("route_repair") or {}).get("known_tool") is False)}


HARMONY_MARKERS = ("<|channel|>", "<|call|>", "<|start|>", "<|message|>", "to=functions.", "<|constrain|>")


def response_summary(model: vm.VertexModel, raw: bytes, stream: bool) -> dict:
    """What the model returned, in counts: finish reason(s), tool calls, visible text and reasoning characters.
    It's diagnostic only (why a turn ended), and no content is stored."""
    out = {"finish_reasons": [], "tool_calls": 0, "text_chars": 0, "reasoning_chars": 0}
    text_parts: list[str] = []
    events = list(_sse_payloads(raw)) if stream else []
    if not stream:
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return out
        events = doc if isinstance(doc, list) else [doc]
    tool_ids = set()
    for ev in events:
        if not isinstance(ev, dict):
            continue
        if model.wire == "openai_chat":
            for choice in ev.get("choices") or []:
                part = choice.get("delta") or choice.get("message") or {}
                out["text_chars"] += len(part.get("content") or "")
                text_parts.append(part.get("content") or "")
                out["reasoning_chars"] += len(part.get("reasoning_content") or part.get("reasoning") or "")
                for call in part.get("tool_calls") or []:
                    tool_ids.add((call.get("index"), call.get("id")) if stream else id(call))
                if choice.get("finish_reason"):
                    out["finish_reasons"].append(choice["finish_reason"])
        elif model.wire == "anthropic":
            kind = ev.get("type")
            if kind == "content_block_start" and (ev.get("content_block") or {}).get("type") == "tool_use":
                out["tool_calls"] += 1
            elif kind == "content_block_delta":
                delta = ev.get("delta") or {}
                out["text_chars"] += len(delta.get("text") or "")
                out["reasoning_chars"] += len(delta.get("thinking") or "")
            elif kind == "message_delta" and (ev.get("delta") or {}).get("stop_reason"):
                out["finish_reasons"].append(ev["delta"]["stop_reason"])
            elif "content" in ev and "stop_reason" in ev:  # non-streamed message
                for block in ev.get("content") or []:
                    if block.get("type") == "tool_use":
                        out["tool_calls"] += 1
                    out["text_chars"] += len(block.get("text") or "")
                    out["reasoning_chars"] += len(block.get("thinking") or "")
                if ev.get("stop_reason"):
                    out["finish_reasons"].append(ev["stop_reason"])
        else:
            for cand in ev.get("candidates") or []:
                for part in (cand.get("content") or {}).get("parts") or []:
                    if part.get("functionCall"):
                        out["tool_calls"] += 1
                    elif part.get("thought"):
                        out["reasoning_chars"] += len(part.get("text") or "")
                    else:
                        out["text_chars"] += len(part.get("text") or "")
                if cand.get("finishReason"):
                    out["finish_reasons"].append(cand["finishReason"])
    if model.wire == "openai_chat":
        out["tool_calls"] = len(tool_ids)
        text = "".join(text_parts)
        # gpt-oss: tool calls left as raw harmony text in content (not parsed into tool_calls) end the turn early.
        out["harmony_markers_in_text"] = any(m in text for m in HARMONY_MARKERS)
        out["text_head"] = text[:160]
    return out


class WireProxy:
    """One proxy per run. ``base_url`` goes into the OpenCode config;
    ``wire_path`` collects the wire records."""

    def __init__(self, project: str, wire_path: Path, token: Callable[[], str], *,
                 host: str = "127.0.0.1", port: int = 0, upstream_host: str | None = None,
                 opener=urllib.request.urlopen, on_prompt_blocked: Callable[[dict], None] | None = None):
        self.project, self.wire_path, self.token = project, Path(wire_path), token
        # Gemini blocked the prompt: tell the executor (it stops the agent) and refuse later calls without
        # sending them, so OpenCode can't loop on an empty answer.
        self.on_prompt_blocked, self.prompt_blocked = on_prompt_blocked, None
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
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._reply(handler, 400, {"error": "request body is not JSON"})
        except ValueError as exc:
            return self._reply(handler, 400, {"error": str(exc)})
        with self._lock:
            self._index += 1
            index = self._index
        started = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        if self.prompt_blocked is not None:
            self._record(index, started, model, sent, enforced, None, None, None, "prompt_blocked: not sent",
                         extra={"short_circuited": True})
            return self._reply(handler, 400, {"error": {"code": 400, "status": "PROMPT_BLOCKED",
                                                        "message": f"prompt blocked: {self.prompt_blocked.get('blockReason')}"}})
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.token()}"}
        for name in _FORWARD_HEADERS:
            if handler.headers.get(name):
                headers[name] = handler.headers[name]
        upstream_stream = stream if model.upstream_stream is None else model.upstream_stream
        if stream and not upstream_stream:  # e.g. gpt-oss: call Vertex non-streaming, re-stream the result
            sent = dict(sent, stream=False)
            sent.pop("stream_options", None)
        request = urllib.request.Request(self._url(model, upstream_stream), data=json.dumps(sent).encode("utf-8"),
                                         headers=headers, method="POST")
        status, chunks, content_type = None, [], "application/json"
        try:
            response = self.opener(request, timeout=600)
        except urllib.error.HTTPError as exc:
            response = exc
        except OSError as exc:
            self._record(index, started, model, sent, enforced, None, None, None, str(exc))
            return self._reply(handler, 502, {"error": f"upstream unreachable: {exc}"})
        client = {"ok": True}

        def send(data: bytes) -> None:
            """Write to the client unless it already hung up. A hang-up (BrokenPipe / ConnectionReset) stops the
            writes; reading upstream continues so the record still gets the full response and usage."""
            if not client["ok"]:
                return
            try:
                handler.wfile.write(data)
                handler.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                client["ok"] = False
                handler.close_connection = True

        with response:
            status = getattr(response, "status", None) or response.getcode()
            content_type = response.headers.get("Content-Type", content_type)
            if model.repair_text_tool_calls and status == 200:
                # Buffer the whole response, rebuild a tool call the route left as text, then send it.
                raw_all = response.read()
                sent_bytes, repair = repair_text_tool_calls(raw_all, upstream_stream, sent)
                usage, served = parse_response(model, raw_all, upstream_stream)
                if stream and not upstream_stream:
                    sent_bytes, content_type = to_sse(sent_bytes), "text/event-stream"
                summary = response_summary(model, sent_bytes, stream)
                try:
                    handler.send_response(status)
                    handler.send_header("Content-Type", content_type)
                    handler.send_header("Transfer-Encoding", "chunked")
                    handler.end_headers()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    client["ok"] = False
                send(f"{len(sent_bytes):X}\r\n".encode() + sent_bytes + b"\r\n")
                self._record(index, started, model, sent, enforced, usage, served, status, None,
                             extra={"response_summary": summary, "client_disconnected": not client["ok"],
                                    "response_bytes": len(raw_all), "route_repair": repair,
                                    "upstream_response_summary": response_summary(model, raw_all, upstream_stream),
                                    "upstream_stream": upstream_stream,
                                    "upstream_raw": self._save_raw(index, raw_all, upstream_stream)})
                send(b"0\r\n\r\n")
                return
            try:
                handler.send_response(status)
                handler.send_header("Content-Type", content_type)
                handler.send_header("Transfer-Encoding", "chunked")
                handler.end_headers()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                client["ok"] = False
                handler.close_connection = True
            while True:
                piece = response.read1(65536) if hasattr(response, "read1") else response.read(65536)
                if not piece:
                    break
                chunks.append(piece)
                send(f"{len(piece):X}\r\n".encode() + piece + b"\r\n")
            # Record before the final chunk, so the record exists once the client has the full reply.
            raw_all = b"".join(chunks)
            usage, served = parse_response(model, raw_all, upstream_stream) if status == 200 else (None, None)
            blocked = prompt_feedback(model, raw_all, upstream_stream) if status == 200 else None
            extra = {"response_summary": response_summary(model, raw_all, upstream_stream) if status == 200 else None,
                     "prompt_blocked": blocked,
                     "client_disconnected": not client["ok"], "response_bytes": len(raw_all),
                     "usage_events": usage_events(model, raw_all, upstream_stream) if status == 200 else None}
            if model.repair_text_tool_calls:  # gpt-oss error bodies too: what the route sent, byte for byte
                extra.update({"route_repair": None, "upstream_response_summary": None, "upstream_stream": upstream_stream,
                              "upstream_raw": self._save_raw(index, raw_all, upstream_stream)})
            self._record(index, started, model, sent, enforced, usage, served, status, None, extra=extra)
            send(b"0\r\n\r\n")
            if blocked is not None and self.prompt_blocked is None:
                self.prompt_blocked = blocked
                if self.on_prompt_blocked is not None:
                    try:
                        self.on_prompt_blocked(blocked)
                    except Exception:  # stopping the agent must never break the proxy
                        pass

    def _save_raw(self, index: int, raw: bytes, stream: bool) -> str | None:
        """gpt-oss only: the upstream response exactly as Vertex sent it, next to the wire file
        (``upstream-raw/<call_index>.sse|json``). Returns the path relative to the wire file's directory."""
        rel = Path("upstream-raw") / f"{index:04d}.{'sse' if stream else 'json'}"
        try:
            (self.wire_path.parent / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.wire_path.parent / rel).write_bytes(raw)
        except OSError:
            return None
        return str(rel)

    def _record(self, index, started, model, sent, enforced, usage, served, status, error, extra=None) -> None:
        tools = sent.get("tools")
        record = {
            "schema": WIRE_SCHEMA, "call_index": index, "ts": started, "provider_wire": model.wire,
            "call_role": "main" if isinstance(tools, list) and tools else "side",
            "requested_model": model.vertex_id, "upstream_model": served,
            "request": sent, "response_usage": usage, "status": status,
            "route": model.key, "thinking_enforced": enforced, "cost_usd": None, "cost_basis": None,
        }
        if error:
            record["error"] = error
        record.update(extra or {})
        if usage is not None:
            try:
                detail = vm.cost_detail(model, usage_from_response(model.wire, usage, index))
                record["cost_usd"], record["cost_basis"] = detail["usd"], detail["basis"]
            except TraceError as exc:
                record["usage_error"] = exc.code
        with self._lock, self.wire_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
