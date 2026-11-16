"""Repair gpt-oss tool calls that the Vertex chat route leaves as text (SEA-105).

The Vertex ``gpt-oss-120b-maas`` OpenAI-compatible route sometimes returns a
turn whose tool call is only text: Harmony output such as
``commentary to=functions.read <|message|>{"filePath": ...}``, or a bare
JSON arguments object at the end of the reasoning (``Let's read test
file.{"filePath": ...}``). It sends ``finish_reason: "stop"``, no structured
``tool_calls`` and no visible content, so OpenCode ends the turn. This module
rebuilds the structured call **before OpenCode sees the response**, in the
recording proxy.

It is conservative:
- It only repairs a response that has finish_reason ``stop``, no
  ``tool_calls``, no visible content, a request that offered tools, and a
  reasoning/content text that **ends** with a JSON object.
- The tool name comes from an explicit Harmony ``to=functions.<name>``
  recipient, or else from the request's tool schemas: the JSON's keys must
  fit exactly one tool (keys within its properties, its required keys all
  present). Anything ambiguous or unknown is left as it is; the trial then
  ends ``route_truncated``.
- Every repair is reported to the caller, which records it on the wire record
  (``route_repair``).
"""

from __future__ import annotations

import hashlib
import json
import re

HARMONY_RECIPIENT = re.compile(r"to=functions\.([A-Za-z0-9_\-.]+)")
HARMONY_TOKENS = re.compile(r"<\|[a-z_]+\|>")
MAX_TAIL = 40          # characters allowed after the JSON object (harmony tokens / punctuation / whitespace)


def _tools(request: dict) -> dict[str, dict]:
    out = {}
    for tool in request.get("tools") or []:
        fn = tool.get("function") if isinstance(tool, dict) else None
        if isinstance(fn, dict) and fn.get("name"):
            params = fn.get("parameters") or {}
            out[fn["name"]] = {"properties": set((params.get("properties") or {}).keys()),
                               "required": set(params.get("required") or [])}
    return out


def _last_json_object(text: str) -> tuple[dict, int] | None:
    """The JSON object that ends the text (only a short tail may follow), with its start offset."""
    decoder = json.JSONDecoder()
    cleaned_tail_ok = lambda tail: len(HARMONY_TOKENS.sub("", tail).strip(" \t\r\n.`")) == 0 and len(tail) <= MAX_TAIL
    for start in range(len(text) - 1, -1, -1):
        if text[start] != "{":
            continue
        try:
            obj, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and cleaned_tail_ok(text[end:]):
            return obj, start
    return None


def extract_tool_call(text: str, request: dict) -> dict | None:
    """``{"name", "arguments", "method"}`` for the tool call written at the end of ``text``, or None."""
    tools = _tools(request)
    if not tools or not text:
        return None
    found = _last_json_object(text)
    if found is None:
        return None
    args, start = found
    recipients = HARMONY_RECIPIENT.findall(text[:start])
    if recipients:
        name = recipients[-1]
        if name in tools:
            return {"name": name, "arguments": args, "method": "harmony_recipient"}
        return None
    keys = set(args)
    fits = [n for n, t in tools.items() if keys <= t["properties"] and t["required"] <= keys]
    if len(fits) != 1:
        return None
    return {"name": fits[0], "arguments": args, "method": "schema_match"}


def _sse(events: list[dict]) -> bytes:
    return b"".join(b"data: " + json.dumps(e).encode("utf-8") + b"\n\n" for e in events) + b"data: [DONE]\n\n"


def _parse_stream(raw: bytes) -> list[dict]:
    events = []
    for block in raw.decode("utf-8", "replace").replace("\r\n", "\n").split("\n\n"):
        data = "\n".join(line[5:].strip() for line in block.split("\n") if line.startswith("data:"))
        if data and data != "[DONE]":
            try:
                events.append(json.loads(data))
            except json.JSONDecodeError:
                continue
    return events


def repair(raw: bytes, stream: bool, request: dict) -> tuple[bytes, dict | None]:
    """``(bytes to send the client, repair record or None)``. Unrepaired responses come back unchanged."""
    if stream:
        events = _parse_stream(raw)
        reasoning, content, finish, has_calls, usage, meta = [], [], None, False, None, {}
        for ev in events:
            meta = meta or {k: ev[k] for k in ("id", "object", "created", "model") if k in ev}
            for choice in ev.get("choices") or []:
                delta = choice.get("delta") or {}
                reasoning.append(delta.get("reasoning_content") or delta.get("reasoning") or "")
                content.append(delta.get("content") or "")
                has_calls |= bool(delta.get("tool_calls"))
                finish = choice.get("finish_reason") or finish
            if isinstance(ev.get("usage"), dict):
                usage = ev["usage"]
        reasoning, content = "".join(reasoning), "".join(content)
    else:
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return raw, None
        choice = (doc.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
        content = message.get("content") or ""
        has_calls, finish, usage = bool(message.get("tool_calls")), choice.get("finish_reason"), doc.get("usage")
    visible = HARMONY_TOKENS.sub("", content).strip()
    if finish != "stop" or has_calls or not request.get("tools"):
        return raw, None
    if visible and not HARMONY_RECIPIENT.search(content):
        return raw, None  # a real visible answer: not a lost tool call
    call = None
    for source, text in (("content", content), ("reasoning", reasoning)):
        call = extract_tool_call(text, request)
        if call:
            call["source"] = source
            break
    if call is None:
        return raw, None
    arguments = json.dumps(call["arguments"])
    call_id = "call_route_" + hashlib.sha256((call["name"] + arguments).encode()).hexdigest()[:16]
    tool_call = {"id": call_id, "type": "function", "function": {"name": call["name"], "arguments": arguments}}
    record = {"applied": True, "tool": call["name"], "method": call["method"], "source": call["source"],
              "original_finish_reason": finish}
    if stream:
        base = {**meta, "object": "chat.completion.chunk"}
        out = [dict(base, choices=[{"index": 0, "delta": {"role": "assistant", "reasoning_content": reasoning}}]),
               dict(base, choices=[{"index": 0, "delta": {"tool_calls": [dict(tool_call, index=0)]}}]),
               dict(base, choices=[{"index": 0, "delta": {}, "finish_reason": "tool_calls"}])]
        if usage is not None:
            out.append(dict(base, choices=[], usage=usage))
        return _sse(out), record
    message = dict(message, content=None, tool_calls=[tool_call])
    doc["choices"][0] = dict(choice, message=message, finish_reason="tool_calls")
    return json.dumps(doc).encode("utf-8"), record
