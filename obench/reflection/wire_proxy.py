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

Calls without tools are tagged ``call_role: "side"``. At the OpenCode pin
those are title, summary, and compaction calls; every agent step carries
tools. Compaction (and a title call that replays earlier turns) copies
assistant reasoning, signatures included, into a request whose system prompt
is not the main conversation. Vertex answers 400 ``Invalid signature in
thinking block`` / ``bound to a different conversation``. Side requests that
still carry such a block are sent with ``thinking.block_binding
.prefix_mismatch_behavior=drop_block`` and beta
``thinking-binding-controls-2026-08-01`` (the H2 proxy's
``apply_block_binding``). Main turns never get that control.

The compaction response's own thinking block is signed for the side
request. OpenCode replays it on the next main turn, and Vertex answers
400 ``Invalid signature in thinking block``. This proxy remembers every
thinking ``signature`` and redacted_thinking ``data`` from a side response
(SSE or JSON) for the trial, and on a later main turn removes only those
blocks. A main turn with none of them is the bytes ``prepare_request``
already produced. stdlib plus ``apply_block_binding``.
"""

from __future__ import annotations

import http.client
import json
import os
import re
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
from obench.reflection.patches import PatchError, apply_patch, validate_patch
from obench.reflection.trace import WIRE_SCHEMA, TraceError, usage_from_response
from thesis.ab.vertex_anthropic_proxy import BLOCK_BINDING_BETA, BLOCK_BINDING_ENV, apply_block_binding

ANTHROPIC_VERSION = "vertex-2023-10-16"
_FORWARD_HEADERS = ("anthropic-beta",)
_ANTHROPIC_THINKING_CONFLICTS = ("temperature", "top_k", "top_p")
# OpenCode pin ba54cee (1.1.61) agent prompts. Matched on the system prompt
# first so a compaction replay of the user's words cannot re-label the call.
_TITLE_SYSTEM = re.compile(r"you are a title generator", re.IGNORECASE)
_SUMMARY_SYSTEM = re.compile(
    r"summarize what was done in this conversation|write like a pull request description", re.IGNORECASE)
_COMPACTION_SYSTEM = re.compile(r"tasked with summarizing conversations", re.IGNORECASE)
_TITLE_USER = re.compile(r"generate a title for this conversation|the following is the text to summarize", re.IGNORECASE)
_COMPACTION_USER = re.compile(r"provide a detailed prompt for continuing our conversation above", re.IGNORECASE)
_THINKING_SIGNATURE_RE = re.compile(
    r"invalid\W{0,3}signature\W{0,3}in\W{0,3}thinking\W{0,3}block", re.IGNORECASE)


def side_binding_mode() -> str | None:
    """Reflection default: ``drop_block`` on side requests.

    ``OBENCH_THINKING_BLOCK_BINDING`` unset or ``drop_block`` enables it. Any
    other value (``off``, empty) disables it. The H2 proxy reads the same
    variable and stays off when it is unset; this default applies only here,
    and only to side requests.
    """
    raw = os.environ.get(BLOCK_BINDING_ENV)
    if raw is None or raw.strip() == "drop_block":
        return "drop_block"
    return None


def _text_blocks(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        return []
    out = []
    for block in value:
        if isinstance(block, str):
            out.append(block)
        elif isinstance(block, dict) and isinstance(block.get("text"), str):
            out.append(block["text"])
    return out


def _system_text(body: dict) -> str:
    parts = _text_blocks(body.get("system"))
    for message in body.get("messages") or []:
        if isinstance(message, dict) and message.get("role") == "system":
            parts.extend(_text_blocks(message.get("content")))
    return "\n".join(parts)


def _user_text(body: dict) -> str:
    parts = []
    for message in body.get("messages") or []:
        if isinstance(message, dict) and message.get("role") == "user":
            parts.extend(_text_blocks(message.get("content")))
    return "\n".join(parts)


def classify_side_kind(body: dict) -> str:
    """``title``, ``summary``, ``compaction``, or ``unknown``.

    OpenCode's title agent (``title.txt``, including the message-summary call
    that uses that agent), summary agent (``summary.txt``), and compaction
    agent (``compaction.txt`` plus the continuation prompt). System text wins
    over user text so a replayed conversation cannot relabel compaction.
    """
    if not isinstance(body, dict):
        return "unknown"
    system, user = _system_text(body), _user_text(body)
    if _TITLE_SYSTEM.search(system):
        return "title"
    if _SUMMARY_SYSTEM.search(system):
        return "summary"
    if _COMPACTION_SYSTEM.search(system):
        return "compaction"
    if _COMPACTION_USER.search(user):
        return "compaction"
    if _TITLE_USER.search(user):
        return "title"
    if _SUMMARY_SYSTEM.search(user):
        return "summary"
    return "unknown"


def is_side_request(body: dict) -> bool:
    tools = body.get("tools") if isinstance(body, dict) else None
    return not (isinstance(tools, list) and tools)


def with_binding_beta(header: str | None) -> str:
    parts = [p.strip() for p in (header or "").split(",") if p.strip()]
    if BLOCK_BINDING_BETA not in parts:
        parts.append(BLOCK_BINDING_BETA)
    return ",".join(parts)


def bind_side_request(model: vm.VertexModel, sent: dict, beta: str | None) -> tuple[str | None, str | None]:
    """Apply drop_block to an Anthropic side request that replays thinking.

    Returns ``(binding, beta header to send)``. Main turns, non-Anthropic
    wires, and side requests with no thinking block are unchanged: binding is
    None for a main/non-Anthropic call and ``off`` for an Anthropic side call
    that was not rewritten. ``beta`` is the header actually sent.
    """
    if model.wire != "anthropic" or not is_side_request(sent):
        return None, beta
    mode = side_binding_mode()
    applied = apply_block_binding(sent, mode=mode) if mode else None
    if applied:
        return applied, with_binding_beta(beta)
    return "off", beta


def is_thinking_signature_error(raw: bytes | str | None) -> bool:
    if not raw:
        return False
    text = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
    return _THINKING_SIGNATURE_RE.search(text) is not None


# Kept only when stripping the side-signed thinking block would leave an
# assistant message with no content. The message itself is never dropped:
# Anthropic rejects an empty content array, and a missing message would
# change the conversation without a trace. Summary text, when present, stays
# instead of this placeholder.
EMPTY_ASSISTANT_AFTER_STRIP = "[omitted side-signed thinking]"


def _remember_signature(found: set[str], value) -> None:
    if isinstance(value, str) and value:
        found.add(value)


def _collect_content_signatures(content, found: set[str]) -> None:
    if not isinstance(content, list):
        return
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "thinking":
            _remember_signature(found, block.get("signature"))
        elif block.get("type") == "redacted_thinking":
            _remember_signature(found, block.get("data"))


def response_thinking_signatures(model: vm.VertexModel, raw: bytes, stream: bool) -> set[str]:
    """Thinking ``signature`` values and redacted_thinking ``data`` in one Anthropic response.

    Streamed signatures are concatenated per content block (``signature_delta``
    can arrive in more than one event). Empty strings are not recorded.
    """
    if model.wire != "anthropic" or not raw:
        return set()
    found: set[str] = set()
    if not stream:
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return set()
        docs = doc if isinstance(doc, list) else [doc]
        for item in docs:
            if isinstance(item, dict):
                _collect_content_signatures(item.get("content"), found)
        return found
    partial: dict[int, dict] = {}
    order: list[int] = []
    for event in _sse_payloads(raw):
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        if kind == "content_block_start":
            idx = event.get("index")
            if not isinstance(idx, int):
                idx = len(order)
            block = event.get("content_block") if isinstance(event.get("content_block"), dict) else {}
            partial[idx] = {"type": block.get("type"), "signature": block.get("signature") or "",
                            "data": block.get("data") or "", "deltas": []}
            if idx not in order:
                order.append(idx)
        elif kind == "content_block_delta":
            idx = event.get("index")
            if not isinstance(idx, int):
                idx = order[-1] if order else 0
            delta = event.get("delta") if isinstance(event.get("delta"), dict) else {}
            slot = partial.setdefault(idx, {"type": None, "signature": "", "data": "", "deltas": []})
            if idx not in order:
                order.append(idx)
            if delta.get("type") == "signature_delta":
                piece = delta.get("signature")
                if isinstance(piece, str) and piece:
                    slot["deltas"].append(piece)
            piece = delta.get("data")
            if isinstance(piece, str) and piece:
                slot["data"] = f"{slot.get('data') or ''}{piece}"
        elif isinstance(event.get("content"), list):
            _collect_content_signatures(event.get("content"), found)
    for idx in order:
        slot = partial.get(idx) or {}
        kind = slot.get("type")
        signature = "".join(slot.get("deltas") or []) or slot.get("signature") or ""
        if kind == "redacted_thinking":
            _remember_signature(found, slot.get("data"))
        elif kind == "thinking" or slot.get("deltas"):
            _remember_signature(found, signature)
    return found


def _block_replay_key(block: dict) -> str | None:
    """The value a later request uses to replay this block: thinking signature, or redacted data."""
    if block.get("type") == "thinking" and isinstance(block.get("signature"), str) and block["signature"]:
        return block["signature"]
    if block.get("type") == "redacted_thinking" and isinstance(block.get("data"), str) and block["data"]:
        return block["data"]
    return None


def strip_side_thinking_blocks(sent: dict, signatures: set[str]) -> tuple[dict, int]:
    """Drop thinking / redacted_thinking blocks whose replay key is in ``signatures``.

    Returns ``(body, removed)``. When ``removed`` is 0 the original dict is
    returned, so ``json.dumps`` matches what ``prepare_request`` produced.
    Summary text and every other block stay, including thinking signed in the
    main conversation. An assistant message that would have no content left
    is kept, with one text block ``EMPTY_ASSISTANT_AFTER_STRIP``; the message
    is not removed.
    """
    if not signatures or not isinstance(sent, dict):
        return sent, 0
    messages = sent.get("messages")
    if not isinstance(messages, list):
        return sent, 0
    removed = 0
    changed = False
    new_messages = []
    for message in messages:
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            new_messages.append(message)
            continue
        kept = []
        local = 0
        for block in content:
            key = _block_replay_key(block) if isinstance(block, dict) else None
            if key is not None and key in signatures:
                local += 1
                continue
            kept.append(block)
        if local == 0:
            new_messages.append(message)
            continue
        changed = True
        removed += local
        if not kept:
            kept = [{"type": "text", "text": EMPTY_ASSISTANT_AFTER_STRIP}]
        new_messages.append(dict(message, content=kept))
    if not changed:
        return sent, 0
    out = dict(sent)
    out["messages"] = new_messages
    return out, removed


def signature_400_count(wire_records: list[dict]) -> int:
    return sum(1 for w in wire_records if w.get("thinking_signature_reject"))


def stripped_side_thinking_total(wire_records: list[dict]) -> int:
    total = 0
    for record in wire_records:
        count = record.get("stripped_side_thinking_blocks") or 0
        if isinstance(count, int) and not isinstance(count, bool):
            total += count
    return total


def side_kind_counts(wire_records: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for record in wire_records:
        if record.get("call_role") != "side":
            continue
        kind = record.get("side_kind") or "unknown"
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def thinking_binding_seen(wire_records: list[dict]) -> str | None:
    """``drop_block`` if any call applied it, else ``off`` if a side call recorded that, else None."""
    values = [w.get("thinking_block_binding") for w in wire_records]
    if "drop_block" in values:
        return "drop_block"
    if "off" in values:
        return "off"
    return None


def terminating_side_signature(wire_records: list[dict]) -> dict | None:
    """The last model call was a side request rejected for a foreign thinking signature."""
    if not wire_records:
        return None
    last = max(wire_records, key=lambda w: w.get("call_index") or 0)
    if last.get("call_role") != "side" or not last.get("thinking_signature_reject"):
        return None
    return {"call_index": last.get("call_index"), "side_kind": last.get("side_kind"),
            "status": last.get("status"), "thinking_block_binding": last.get("thinking_block_binding"),
            "anthropic_beta": last.get("anthropic_beta")}


def post_compaction_detail(wire_records: list[dict]) -> dict | None:
    """A breaking main-turn thinking-signature 400 that follows a side call.

    Precedence, applied by ``cell_executor.finish_trial``:

    1. ``side_thinking_signature`` wins when the last call is itself a side
       signature 400 and the last step still shows a tool call. This function
       returns None in that case so the side status is not overwritten.
    2. ``post_compaction_signature`` is this detail: the 400 is on a main turn,
       no later main call succeeded, and some earlier call in the trial was a
       side request. It outranks ``upstream_4xx`` and ``agent_exit_pending_tool``.
    3. Anything else stays ``upstream_4xx`` (or a recovered covariate).

    A main-turn signature 400 with no side call earlier in the trial is not
    this status.
    """
    if not wire_records or terminating_side_signature(wire_records) is not None:
        return None
    breaking = classify_4xx(wire_records)["breaking"]
    if not breaking:
        return None
    by_index = {w.get("call_index"): w for w in wire_records}
    hits = []
    for call in breaking:
        record = by_index.get(call.get("call_index"))
        if not record or record.get("call_role") == "side" or not record.get("thinking_signature_reject"):
            continue
        prior = [w for w in wire_records if w.get("call_role") == "side"
                 and (w.get("call_index") or 0) < (record.get("call_index") or 0)]
        if not prior:
            continue
        nearest = max(prior, key=lambda w: w.get("call_index") or 0)
        hits.append({"call_index": record.get("call_index"), "status": record.get("status"),
                     "prior_side_call_index": nearest.get("call_index"),
                     "prior_side_kind": nearest.get("side_kind")})
    if not hits:
        return None
    return {"call_index": hits[-1]["call_index"], "status": hits[-1]["status"],
            "prior_side_call_index": hits[-1]["prior_side_call_index"],
            "prior_side_kind": hits[-1]["prior_side_kind"], "calls": hits}


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


def provider_blocked(wire_records: list[dict]) -> dict | None:
    """The provider blocked the trial's prompt (Gemini ``promptFeedback.blockReason``; status ``provider_blocked``):
    neither pass nor fail, nor route_truncated / upstream_4xx / timeout. The raw blockReason and
    blockReasonMessage are kept. Legacy records, written before the field existed (2026-11-17) and so without a
    ``provider_blocked`` key, are recognised when every answered main call came back empty (no candidates: no
    finish reason, text, thinking or tool call); that is marked ``inferred``. A current record (key present, null:
    no blockReason) with empty replies is never inferred as blocked; that trial is ``route_truncated``."""
    main = sorted((w for w in wire_records if w.get("call_role") != "side" and w.get("status") == 200),
                  key=lambda w: w.get("call_index") or 0)
    # Researcher ruling 2026-11-17: classified on the trial's last answered call (later calls are refused by the
    # proxy without being sent, so a block is always the last answered call).
    if main and main[-1].get("provider_blocked"):
        return dict(main[-1]["provider_blocked"], call_index=main[-1].get("call_index"),
                    calls_blocked=sum(1 for x in wire_records if x.get("provider_blocked")))
    gemini = [w for w in main if w.get("provider_wire") == "gemini"]
    # Legacy records only: a record written since the field existed carries the "provider_blocked" key (null when
    # Vertex sent no blockReason). Empty replies there are not a block; they end route_truncated (infra).
    legacy = all("provider_blocked" not in w for w in gemini)
    if gemini and legacy and len(gemini) == len(main) and all(
            not s.get("finish_reasons") and not s.get("text_chars") and not s.get("reasoning_chars")
            and not s.get("tool_calls") for s in (w.get("response_summary") or {} for w in gemini)):
        return {"blockReason": None, "inferred": True, "call_index": gemini[0].get("call_index"),
                "calls_blocked": len(gemini)}
    return None


REFUSAL_FINISHES = {"anthropic": ("refusal",), "gemini": ("SAFETY",), "openai_chat": ("content_filter",)}


def model_refused(wire_records: list[dict]) -> dict | None:
    """The model's output was refused or stopped for safety at any point of the trial: Anthropic
    ``stop_reason: "refusal"`` (with ``stop_details``), or a Gemini candidate with ``finishReason: SAFETY``
    (with its ``safetyRatings``). Researcher ruling 2026-11-17: ``model_refused`` is set aside like
    ``provider_blocked`` (neither pass nor fail). Returns the first refusal and every refused call."""
    main = sorted((w for w in wire_records if w.get("call_role") != "side" and w.get("status") == 200),
                  key=lambda w: w.get("call_index") or 0)
    refused = []
    for w in main:
        summary = w.get("response_summary") or {}
        hits = [f for f in summary.get("finish_reasons") or [] if f in REFUSAL_FINISHES.get(w.get("provider_wire"), ())]
        if hits:
            refused.append({"call_index": w.get("call_index"), "stop_reason": hits[0],
                            "stop_details": summary.get("stop_details"), "safety_ratings": summary.get("safety_ratings")})
    if not refused:
        return None
    return dict(refused[0], calls_refused=len(refused), refusals=refused,
                last_call_refused=refused[-1]["call_index"] == main[-1].get("call_index"))


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
    # Nothing came back: a stop with no text/tool call, or (Gemini) no finish reason at all: a reply with no
    # candidates and no blockReason.
    no_candidates = not finishes and last.get("provider_wire") == "gemini"
    empty = (any(f in STOP_REASONS for f in finishes) or no_candidates) and no_call and not summary.get("text_chars")
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
                if (ev.get("delta") or {}).get("stop_details"):
                    out["stop_details"] = ev["delta"]["stop_details"]
            elif "content" in ev and "stop_reason" in ev:  # non-streamed message
                for block in ev.get("content") or []:
                    if block.get("type") == "tool_use":
                        out["tool_calls"] += 1
                    out["text_chars"] += len(block.get("text") or "")
                    out["reasoning_chars"] += len(block.get("thinking") or "")
                if ev.get("stop_reason"):
                    out["finish_reasons"].append(ev["stop_reason"])
                if ev.get("stop_details"):
                    out["stop_details"] = ev["stop_details"]
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
                    if cand["finishReason"] == "SAFETY" and cand.get("safetyRatings"):
                        out["safety_ratings"] = cand["safetyRatings"]
    if model.wire == "openai_chat":
        out["tool_calls"] = len(tool_ids)
        text = "".join(text_parts)
        # gpt-oss: tool calls left as raw harmony text in content (not parsed into tool_calls) end the turn early.
        out["harmony_markers_in_text"] = any(m in text for m in HARMONY_MARKERS)
        out["text_head"] = text[:160]
    return out


def last_vertex_request(wires: list[dict] | None, live: dict | None = None) -> dict | None:
    """The last Vertex call: send time (``sent_at`` / wire ``ts``), model, and whether a response came back.
    ``live`` is ``last_vertex_request.json``, which exists even when the call never finished a wire line."""
    keys = ("sent_at", "model", "response_arrived", "first_byte_at", "call_index", "status")
    best = None
    if wires:
        wire = max(wires, key=lambda item: item.get("call_index") or 0)
        best = {"sent_at": wire.get("ts"), "model": wire.get("requested_model") or wire.get("upstream_model"),
                "response_arrived": bool(wire.get("response_arrived")), "first_byte_at": wire.get("first_byte_at"),
                "call_index": wire.get("call_index"), "status": wire.get("status")}
    if not live:
        return best
    live_index = live.get("call_index") or 0
    if best is None or live_index > (best.get("call_index") or 0):
        return {k: live.get(k) for k in keys}
    if live_index == best.get("call_index") and live.get("first_byte_at") and not best.get("first_byte_at"):
        best["first_byte_at"] = live.get("first_byte_at")
        best["response_arrived"] = bool(best["response_arrived"] or live.get("response_arrived"))
    return best


class WireProxy:
    """One proxy per run. ``base_url`` goes into the OpenCode config;
    ``wire_path`` collects the wire records."""

    def __init__(self, project: str, wire_path: Path, token: Callable[[], str], *,
                 host: str = "127.0.0.1", port: int = 0, upstream_host: str | None = None,
                 opener=urllib.request.urlopen, patch: dict | None = None, patch_id: str | None = None,
                 on_provider_blocked: Callable[[dict], None] | None = None):
        if (patch is None) != (patch_id is None):
            raise ValueError("patch and patch_id go together")
        if patch is not None:
            reasons = validate_patch(patch)
            if reasons:
                raise PatchError("; ".join(reasons))
        self.patch, self.patch_id = patch, patch_id
        self.project, self.wire_path, self.token = project, Path(wire_path), token
        # Gemini blocked the prompt: tell the executor (it stops the agent) and refuse later calls without
        # sending them, so OpenCode can't loop on an empty answer.
        self.on_provider_blocked, self.provider_blocked = on_provider_blocked, None
        self.client_resets: list[str] = []  # client-side socket resets outside a call (counted per trial)
        self.upstream_host, self.opener = upstream_host, opener
        self._lock, self._index, self._last = threading.Lock(), 0, None
        # Thinking signatures (and redacted_thinking data) returned by side
        # responses in this trial. One proxy is one trial. Main turns drop
        # only blocks whose replay key is in this set.
        self._side_signatures: set[str] = set()
        self.wire_path.parent.mkdir(parents=True, exist_ok=True)
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt, *args):
                return

            def do_POST(self):  # noqa: N802
                proxy.handle(self)

            def handle(self):
                # A client that goes away (OpenCode exiting with a request in flight) resets the socket; that is
                # recorded on the call when it happens mid-response, and is not a proxy crash.
                try:
                    super().handle()
                except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError) as exc:
                    proxy.client_resets.append(f"{type(exc).__name__}: {exc}")

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
        beta = handler.headers.get("anthropic-beta")
        side = is_side_request(sent)
        binding, beta = bind_side_request(model, sent, beta)
        # Main turns never receive drop_block. Strip only blocks signed by an
        # earlier side response. No match leaves ``sent`` as prepare_request
        # (and the patch, if any) built it, so the upstream bytes do not change.
        stripped = 0
        if model.wire == "anthropic" and not side:
            sent, stripped = strip_side_thinking_blocks(sent, self._side_signatures_copy())
        note = {
            "side_kind": classify_side_kind(sent) if side else None,
            "thinking_block_binding": binding,
            "anthropic_beta": beta,
            "thinking_signature_reject": False,
        }
        if not side:
            note["stripped_side_thinking_blocks"] = stripped
        with self._lock:
            self._index += 1
            index = self._index
        started = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        if self.provider_blocked is not None:
            self._record(index, started, model, sent, enforced, None, None, None, "provider_blocked: not sent",
                         extra={"short_circuited": True, **note}, note_last=False)
            return self._reply(handler, 400, {"error": {"code": 400, "status": "PROVIDER_BLOCKED",
                                                        "message": f"provider blocked: {self.provider_blocked.get('blockReason')}"}})
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.token()}"}
        for name in _FORWARD_HEADERS:
            if name == "anthropic-beta":
                if beta:
                    headers[name] = beta
                continue
            if handler.headers.get(name):
                headers[name] = handler.headers[name]
        upstream_stream = stream if model.upstream_stream is None else model.upstream_stream
        if stream and not upstream_stream:  # e.g. gpt-oss: call Vertex non-streaming, re-stream the result
            sent = dict(sent, stream=False)
            sent.pop("stream_options", None)
        request = urllib.request.Request(self._url(model, upstream_stream), data=json.dumps(sent).encode("utf-8"),
                                         headers=headers, method="POST")
        # Written before the upstream call returns, so a hang (no response before the agent cap) is visible
        # even when this request never becomes a finished wire line.
        self._note_last({"sent_at": started, "model": model.vertex_id, "response_arrived": False,
                         "first_byte_at": None, "call_index": index, "status": None})
        status, chunks, content_type, first_byte_at = None, [], "application/json", None
        try:
            response = self.opener(request, timeout=600)
        except urllib.error.HTTPError as exc:
            response = exc
        except OSError as exc:
            self._record(index, started, model, sent, enforced, None, None, None, str(exc),
                         extra=dict(note), response_arrived=False, first_byte_at=None)
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
            # Headers came back: a response arrived, even if the body later hangs or resets.
            self._note_last({"sent_at": started, "model": model.vertex_id, "response_arrived": True,
                             "first_byte_at": first_byte_at, "call_index": index, "status": status})
            if model.repair_text_tool_calls and status == 200:
                # Buffer the whole response, rebuild a tool call the route left as text, then send it.
                try:
                    raw_all, stream_error = response.read(), None
                except (OSError, http.client.HTTPException) as exc:  # reset/incomplete upstream body
                    raw_all, stream_error = getattr(exc, "partial", b"") or b"", f"{type(exc).__name__}: {exc}"
                if raw_all and first_byte_at is None:
                    first_byte_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
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
                if side and status == 200:
                    self._remember_side_signatures(response_thinking_signatures(model, raw_all, upstream_stream))
                self._record(index, started, model, sent, enforced, usage, served, status, None,
                             extra={"response_summary": summary, "client_disconnected": not client["ok"],
                                    "response_bytes": len(raw_all), "route_repair": repair,
                                    "upstream_response_summary": response_summary(model, raw_all, upstream_stream),
                                    "upstream_stream": upstream_stream, "stream_error": stream_error,
                                    "upstream_raw": self._save_raw(index, raw_all, upstream_stream),
                                    **dict(note, thinking_signature_reject=status == 400 and is_thinking_signature_error(raw_all))},
                             response_arrived=True, first_byte_at=first_byte_at)
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
            stream_error = None
            while True:
                try:
                    piece = response.read1(65536) if hasattr(response, "read1") else response.read(65536)
                except (OSError, http.client.HTTPException) as exc:
                    # Vertex reset the stream mid-response. Record it on the call; tell an Anthropic client with
                    # an SSE error event (so the SDK raises instead of ending the turn quietly); then end.
                    stream_error = f"{type(exc).__name__}: {exc}"
                    if model.wire == "anthropic" and status == 200:
                        event = {"type": "error", "error": {"type": "api_error", "message": "upstream stream reset"}}
                        data = b"event: error\ndata: " + json.dumps(event).encode() + b"\n\n"
                        send(f"{len(data):X}\r\n".encode() + data + b"\r\n")
                    break
                if not piece:
                    break
                if first_byte_at is None:
                    first_byte_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
                    self._note_last({"sent_at": started, "model": model.vertex_id, "response_arrived": True,
                                     "first_byte_at": first_byte_at, "call_index": index, "status": status})
                chunks.append(piece)
                send(f"{len(piece):X}\r\n".encode() + piece + b"\r\n")
            # Record before the final chunk, so the record exists once the client has the full reply.
            raw_all = b"".join(chunks)
            if side and status == 200:
                self._remember_side_signatures(response_thinking_signatures(model, raw_all, upstream_stream))
            usage, served = parse_response(model, raw_all, upstream_stream) if status == 200 else (None, None)
            blocked = prompt_feedback(model, raw_all, upstream_stream) if status == 200 else None
            extra = {"response_summary": response_summary(model, raw_all, upstream_stream) if status == 200 else None,
                     "provider_blocked": blocked,
                     "client_disconnected": not client["ok"], "response_bytes": len(raw_all),
                     "stream_error": stream_error,
                     "usage_events": usage_events(model, raw_all, upstream_stream) if status == 200 else None,
                     **dict(note, thinking_signature_reject=status == 400 and is_thinking_signature_error(raw_all))}
            if model.repair_text_tool_calls:  # gpt-oss error bodies too: what the route sent, byte for byte
                extra.update({"route_repair": None, "upstream_response_summary": None, "upstream_stream": upstream_stream,
                              "upstream_raw": self._save_raw(index, raw_all, upstream_stream)})
            self._record(index, started, model, sent, enforced, usage, served, status, None, extra=extra,
                         response_arrived=True, first_byte_at=first_byte_at)
            send(b"0\r\n\r\n")
            if blocked is not None and self.provider_blocked is None:
                self.provider_blocked = blocked
                if self.on_provider_blocked is not None:
                    try:
                        self.on_provider_blocked(blocked)
                    except Exception:  # stopping the agent must never break the proxy
                        pass

    def _side_signatures_copy(self) -> set[str]:
        with self._lock:
            return set(self._side_signatures)

    def _remember_side_signatures(self, found: set[str]) -> None:
        if not found:
            return
        with self._lock:
            self._side_signatures.update(found)

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

    def _note_last(self, payload: dict) -> None:
        """Atomically refresh ``last_vertex_request.json`` beside the wire file. A later call does not
        overwrite an earlier one's in-flight record, and an older call does not clobber a newer one."""
        with self._lock:
            if self._last and (payload.get("call_index") or 0) < (self._last.get("call_index") or 0):
                return
            current = dict(self._last) if self._last and self._last.get("call_index") == payload.get("call_index") else {}
            current.update(payload)
            self._last = current
            path = self.wire_path.with_name("last_vertex_request.json")
            tmp = path.with_name("last_vertex_request.json.tmp")
            body = {k: current.get(k) for k in ("sent_at", "model", "response_arrived", "first_byte_at", "call_index", "status")}
            tmp.write_text(json.dumps(body, sort_keys=True) + "\n", encoding="utf-8")
            os.replace(tmp, path)

    def _record(self, index, started, model, sent, enforced, usage, served, status, error, extra=None, *,
                response_arrived=None, first_byte_at=None, note_last=True) -> None:
        if response_arrived is None:
            response_arrived = status is not None
        tools = sent.get("tools")
        record = {
            "schema": WIRE_SCHEMA, "call_index": index, "ts": started, "provider_wire": model.wire,
            "call_role": "main" if isinstance(tools, list) and tools else "side",
            "requested_model": model.vertex_id, "upstream_model": served,
            "request": sent, "response_usage": usage, "status": status,
            "route": model.key, "thinking_enforced": enforced, "cost_usd": None, "cost_basis": None,
            # when the call finished (response fully read): the timeout ruling asks whether any model call
            # finished in the last minutes before the agent cap
            "ended_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "response_arrived": bool(response_arrived),
            "first_byte_at": first_byte_at,
        }
        if self.patch_id is not None:
            record["patch_id"] = self.patch_id
        if error:
            record["error"] = error
        record.update(extra or {})
        if usage is not None:
            try:
                detail = vm.cost_detail(model, usage_from_response(model.wire, usage, index))
                record["cost_usd"], record["cost_basis"] = detail["usd"], detail["basis"]
            except TraceError as exc:
                record["usage_error"] = exc.code
        if note_last:
            self._note_last({"sent_at": started, "model": model.vertex_id, "response_arrived": bool(response_arrived),
                             "first_byte_at": first_byte_at, "call_index": index, "status": status})
        with self._lock, self.wire_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
