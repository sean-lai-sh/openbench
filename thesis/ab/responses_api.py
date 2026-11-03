"""OpenAI Responses API presentation for the Vertex Anthropic proxy.

Codex CLI speaks only the Responses API (``wire_api = "responses"``; the
chat wire was removed), so the hard-suite Codex arm reaches Claude on Vertex
through ``POST /v1/responses`` on the same proxy the Pi and OpenCode arms use.
The proxy translates the request to an Anthropic Messages body, forwards it
exactly like ``/v1/messages`` (same ledger, same usage parsing, same cost),
and translates the reply back. Token and cost accounting therefore come from
the upstream Anthropic usage, as for the other two arms; the Responses
``usage`` object Codex sees is only a projection of it.

Request mapping (Responses -> Anthropic):

* ``instructions`` and ``developer``/``system`` message items -> ``system``.
* ``message`` items -> user/assistant messages; ``input_text``/``output_text``
  parts -> text blocks; ``input_image`` -> image blocks.
* ``function_call`` -> assistant ``tool_use`` (``call_id`` is the id);
  ``function_call_output`` -> user ``tool_result``.
* ``custom_tool_call`` / ``custom_tool_call_output`` -> the same, with the
  freeform text carried as ``{"input": <text>}``.
* ``reasoning`` items whose ``encrypted_content`` this proxy minted are
  decoded back to the Anthropic thinking blocks (signatures intact); any
  other reasoning item is dropped.
* ``function`` tools -> Anthropic tools; ``custom`` (freeform) tools -> a tool
  with one string field ``input``. Hosted tools (web search, local shell,
  image generation, MCP) cannot be served by Claude on Vertex and are dropped;
  their types are recorded.
* ``reasoning.effort`` -> ``thinking: {"type": "adaptive"}`` plus
  ``output_config.effort`` (the shape the Pi arm sends for Claude);
  ``effort == "none"`` sends no thinking.
* ``prompt_cache_key`` (OpenAI's automatic caching hint) -> ephemeral
  ``cache_control`` on the last system block and the last message block, so
  Claude caches the growing prefix. Recorded per request as
  ``responses_cache_emulation`` (brief row 8: a confound to record).
* ``max_output_tokens`` -> ``max_tokens``; ``parallel_tool_calls == false``
  -> ``tool_choice.disable_parallel_tool_use``. ``store``, ``include``,
  ``text``, ``service_tier``, ``metadata`` and ``client_metadata`` have no
  Anthropic counterpart and are dropped.

Reply mapping (Anthropic -> Responses): text -> ``message`` item, tool_use ->
``function_call`` (or ``custom_tool_call`` for a freeform tool), thinking ->
one ``reasoning`` item whose ``encrypted_content`` round-trips the blocks.
Streaming replies are re-emitted as Responses SSE events, ending in
``response.completed`` (or ``response.incomplete`` on ``max_tokens``).
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field

DEFAULT_MAX_TOKENS = 32000
REASONING_ENVELOPE = "obench-thinking-v1:"
HOSTED_TOOL_TYPES = frozenset({
    "web_search", "web_search_preview", "local_shell", "image_generation",
    "mcp", "file_search", "computer_use_preview", "code_interpreter", "tool_search",
})
_DROPPED_FIELDS = (
    "store", "include", "text", "service_tier", "metadata", "client_metadata",
    "prompt_cache_key", "truncation", "user", "previous_response_id",
)


class ResponsesError(ValueError):
    """The request cannot be represented as an Anthropic Messages body."""


@dataclass
class ResponsesContext:
    """What the reply translator needs to know about the request."""

    custom_tools: frozenset = frozenset()
    dropped_tools: tuple = ()
    dropped_items: tuple = ()
    dropped_fields: tuple = ()
    cache_emulation: bool = False
    thinking: str = "none"

    def record(self) -> dict:
        """Ledger ``identity`` fields for this request."""
        out: dict = {"presentation": "responses"}
        if self.dropped_tools:
            out["responses_dropped_tools"] = list(self.dropped_tools)
        if self.dropped_items:
            out["responses_dropped_items"] = list(self.dropped_items)
        if self.dropped_fields:
            out["responses_dropped_fields"] = list(self.dropped_fields)
        out["responses_cache_emulation"] = self.cache_emulation
        out["responses_thinking"] = self.thinking
        return out


# --- request ----------------------------------------------------------------

def _text_of(part) -> str | None:
    if isinstance(part, str):
        return part
    if isinstance(part, dict) and part.get("type") in {"input_text", "output_text", "text"}:
        text = part.get("text")
        return text if isinstance(text, str) else ""
    return None


def _image_block(part: dict) -> dict | None:
    url = part.get("image_url")
    if isinstance(url, dict):
        url = url.get("url")
    if not isinstance(url, str) or not url:
        return None
    if url.startswith("data:"):
        header, _, data = url.partition(",")
        media = header[5:].split(";", 1)[0]
        return {"type": "image", "source": {"type": "base64", "media_type": media or "image/png", "data": data}}
    return {"type": "image", "source": {"type": "url", "url": url}}


def _content_blocks(content) -> list:
    if content is None:
        return []
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    if not isinstance(content, list):
        return [{"type": "text", "text": str(content)}]
    blocks = []
    for part in content:
        text = _text_of(part)
        if text is not None:
            if text:
                blocks.append({"type": "text", "text": text})
            continue
        if isinstance(part, dict) and part.get("type") == "input_image":
            image = _image_block(part)
            if image is not None:
                blocks.append(image)
    return blocks


def _tool_result_content(output):
    """A ``function_call_output.output`` (string or content parts)."""
    if isinstance(output, str):
        return output
    blocks = _content_blocks(output)
    return blocks if blocks else ""


def _parse_arguments(arguments) -> dict:
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError:
            return {"_raw": arguments}
        return parsed if isinstance(parsed, dict) else {"_raw": parsed}
    return {}


def encode_reasoning(blocks: list) -> str:
    raw = json.dumps(blocks, separators=(",", ":")).encode("utf-8")
    return REASONING_ENVELOPE + base64.b64encode(raw).decode("ascii")


def decode_reasoning(value) -> list | None:
    """Thinking blocks from an ``encrypted_content`` this proxy minted, else None."""
    if not isinstance(value, str) or not value.startswith(REASONING_ENVELOPE):
        return None
    try:
        blocks = json.loads(base64.b64decode(value[len(REASONING_ENVELOPE):]))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(blocks, list):
        return None
    return [b for b in blocks if isinstance(b, dict) and b.get("type") in {"thinking", "redacted_thinking"}]


def _merge(messages: list) -> list:
    merged: list = []
    for message in messages:
        if merged and merged[-1]["role"] == message["role"]:
            merged[-1]["content"].extend(message["content"])
        else:
            merged.append({"role": message["role"], "content": list(message["content"])})
    return merged


def _tool(tool: dict, custom: set, dropped: list) -> dict | None:
    if not isinstance(tool, dict):
        raise ResponsesError("tool entries must be objects")
    kind = tool.get("type") or "function"
    if kind == "function":
        name = tool.get("name")
        if not isinstance(name, str) or not name:
            raise ResponsesError("function tools need a name")
        return {
            "name": name,
            "description": tool.get("description") or "",
            "input_schema": tool.get("parameters") or {"type": "object", "properties": {}},
        }
    if kind == "custom":
        name = tool.get("name")
        if not isinstance(name, str) or not name:
            raise ResponsesError("custom tools need a name")
        custom.add(name)
        return {
            "name": name,
            "description": tool.get("description") or "",
            "input_schema": {
                "type": "object",
                "properties": {"input": {"type": "string", "description": "The raw tool input."}},
                "required": ["input"],
            },
        }
    dropped.append(str(kind))
    return None


def _tool_choice(choice, names: set):
    if choice is None or choice == "auto":
        return {"type": "auto"}
    if choice == "none":
        return {"type": "none"}
    if choice == "required":
        return {"type": "any"}
    if isinstance(choice, dict):
        name = choice.get("name")
        if isinstance(name, str) and name in names:
            return {"type": "tool", "name": name}
        if choice.get("type") in HOSTED_TOOL_TYPES:
            return {"type": "auto"}
    raise ResponsesError(f"unsupported tool_choice {choice!r}")


def _mark_cache(block_list: list) -> None:
    for block in reversed(block_list):
        if isinstance(block, dict) and block.get("type") in {"text", "image", "tool_use", "tool_result"}:
            block["cache_control"] = {"type": "ephemeral"}
            return


def responses_to_anthropic(data: dict) -> tuple[dict, ResponsesContext]:
    """A Responses request body as (Anthropic Messages body, reply context)."""
    if not isinstance(data, dict):
        raise ResponsesError("request body must be an object")
    system: list = []
    instructions = data.get("instructions")
    if isinstance(instructions, str) and instructions:
        system.append({"type": "text", "text": instructions})
    items = data.get("input")
    if isinstance(items, str):
        items = [{"type": "message", "role": "user", "content": items}]
    if items is None:
        items = []
    if not isinstance(items, list):
        raise ResponsesError("input must be a string or a list")

    messages: list = []
    dropped_items: list = []
    for item in items:
        if not isinstance(item, dict):
            raise ResponsesError("each input item must be an object")
        kind = item.get("type") or ("message" if "role" in item else None)
        if kind == "message":
            role = item.get("role")
            blocks = _content_blocks(item.get("content"))
            if role in {"system", "developer"}:
                system.extend(blocks)
            elif role == "assistant":
                if blocks:
                    messages.append({"role": "assistant", "content": blocks})
            elif role == "user":
                if blocks:
                    messages.append({"role": "user", "content": blocks})
            else:
                raise ResponsesError(f"unsupported message role {role!r}")
        elif kind == "function_call":
            messages.append({"role": "assistant", "content": [{
                "type": "tool_use",
                "id": item.get("call_id") or item.get("id") or "call",
                "name": item.get("name") or "",
                "input": _parse_arguments(item.get("arguments")),
            }]})
        elif kind == "custom_tool_call":
            raw = item.get("input")
            messages.append({"role": "assistant", "content": [{
                "type": "tool_use",
                "id": item.get("call_id") or item.get("id") or "call",
                "name": item.get("name") or "",
                "input": {"input": raw if isinstance(raw, str) else json.dumps(raw)},
            }]})
        elif kind in {"function_call_output", "custom_tool_call_output"}:
            messages.append({"role": "user", "content": [{
                "type": "tool_result",
                "tool_use_id": item.get("call_id") or "",
                "content": _tool_result_content(item.get("output")),
            }]})
        elif kind == "reasoning":
            blocks = decode_reasoning(item.get("encrypted_content"))
            if blocks:
                messages.append({"role": "assistant", "content": blocks})
            else:
                dropped_items.append("reasoning")
        else:
            dropped_items.append(str(kind))

    merged = _merge(messages)
    custom: set = set()
    dropped_tools: list = []
    tools = []
    for tool in data.get("tools") or []:
        converted = _tool(tool, custom, dropped_tools)
        if converted is not None:
            tools.append(converted)

    out: dict = {"messages": merged}
    if system:
        out["system"] = system
    max_tokens = data.get("max_output_tokens")
    out["max_tokens"] = (
        int(max_tokens)
        if isinstance(max_tokens, (int, float)) and not isinstance(max_tokens, bool) and max_tokens > 0
        else DEFAULT_MAX_TOKENS
    )
    if isinstance(data.get("model"), str):
        out["model"] = data["model"]
    if data.get("stream") is True:
        out["stream"] = True
    if tools:
        out["tools"] = tools
        names = {tool["name"] for tool in tools}
        choice = _tool_choice(data.get("tool_choice"), names)
        if data.get("parallel_tool_calls") is False and choice.get("type") in {"auto", "any", "tool"}:
            choice["disable_parallel_tool_use"] = True
        out["tool_choice"] = choice
    for key in ("temperature", "top_p"):
        if key in data and data[key] is not None:
            out[key] = data[key]

    thinking = "none"
    reasoning = data.get("reasoning")
    effort = reasoning.get("effort") if isinstance(reasoning, dict) else None
    if isinstance(effort, str) and effort and effort != "none":
        out["thinking"] = {"type": "adaptive"}
        out["output_config"] = {"effort": "low" if effort == "minimal" else effort}
        thinking = f"adaptive:{out['output_config']['effort']}"

    cache_emulation = isinstance(data.get("prompt_cache_key"), str) and bool(data["prompt_cache_key"])
    if cache_emulation:
        if system:
            _mark_cache(system)
        if merged:
            _mark_cache(merged[-1]["content"])

    dropped_fields = tuple(key for key in _DROPPED_FIELDS if key in data)
    return out, ResponsesContext(
        custom_tools=frozenset(custom),
        dropped_tools=tuple(dropped_tools),
        dropped_items=tuple(dropped_items),
        dropped_fields=dropped_fields,
        cache_emulation=cache_emulation,
        thinking=thinking,
    )


# --- reply ------------------------------------------------------------------

def _int(value) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


def _cache_write(usage: dict) -> int:
    if isinstance(usage.get("cache_creation_input_tokens"), (int, float)):
        return _int(usage["cache_creation_input_tokens"])
    creation = usage.get("cache_creation")
    if isinstance(creation, dict):
        return sum(_int(v) for v in creation.values())
    return 0


def responses_usage(usage: dict | None) -> dict:
    """Anthropic usage as a Responses ``usage`` object.

    ``input_tokens`` = uncached + cache read + cache write (OpenAI counts every
    prompt token there); ``input_tokens_details.cached_tokens`` = cache read.
    The Anthropic counters are kept alongside so nothing is lost.
    """
    usage = usage if isinstance(usage, dict) else {}
    uncached = _int(usage.get("input_tokens"))
    output = _int(usage.get("output_tokens"))
    cache_read = _int(usage.get("cache_read_input_tokens"))
    cache_write = _cache_write(usage)
    prompt = uncached + cache_read + cache_write
    return {
        "input_tokens": prompt,
        "input_tokens_details": {"cached_tokens": cache_read},
        "output_tokens": output,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": prompt + output,
        "cache_read_input_tokens": cache_read,
        "cache_creation_input_tokens": cache_write,
    }


def _merge_usage(parts: list) -> dict:
    merged: dict = {}
    for part in parts:
        if isinstance(part, dict):
            for key, value in part.items():
                if value is not None:
                    merged[key] = value
    return merged


def _item_id(prefix: str, seed: str, index: int) -> str:
    return f"{prefix}_{seed}_{index}"


def _output_items(content: list, ctx: ResponsesContext, seed: str) -> list:
    items: list = []
    thinking: list = []

    def flush_thinking():
        if not thinking:
            return
        summary = [
            {"type": "summary_text", "text": block.get("thinking") or ""}
            for block in thinking if block.get("type") == "thinking" and block.get("thinking")
        ]
        items.append({
            "type": "reasoning",
            "id": _item_id("rs", seed, len(items)),
            "summary": summary,
            "encrypted_content": encode_reasoning(list(thinking)),
        })
        thinking.clear()

    text_parts: list = []

    def flush_text():
        if not text_parts:
            return
        items.append({
            "type": "message",
            "id": _item_id("msg", seed, len(items)),
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": "".join(text_parts), "annotations": []}],
        })
        text_parts.clear()

    for block in content or []:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind in {"thinking", "redacted_thinking"}:
            flush_text()
            thinking.append(block)
            continue
        flush_thinking()
        if kind == "text" and isinstance(block.get("text"), str):
            text_parts.append(block["text"])
        elif kind == "tool_use":
            flush_text()
            items.append(tool_item(block, ctx, _item_id("fc", seed, len(items))))
    flush_thinking()
    flush_text()
    return items


def tool_item(block: dict, ctx: ResponsesContext, item_id: str) -> dict:
    name = block.get("name") or ""
    arguments = block.get("input") if isinstance(block.get("input"), dict) else {}
    call_id = block.get("id") or item_id
    if name in ctx.custom_tools:
        raw = arguments.get("input")
        return {
            "type": "custom_tool_call",
            "id": item_id,
            "call_id": call_id,
            "name": name,
            "input": raw if isinstance(raw, str) else json.dumps(arguments),
            "status": "completed",
        }
    return {
        "type": "function_call",
        "id": item_id,
        "call_id": call_id,
        "name": name,
        "arguments": json.dumps(arguments, separators=(",", ":")),
        "status": "completed",
    }


def _status(stop_reason) -> tuple[str, dict | None]:
    if stop_reason == "max_tokens":
        return "incomplete", {"reason": "max_output_tokens"}
    if stop_reason == "refusal":
        return "incomplete", {"reason": "content_filter"}
    return "completed", None


def anthropic_message_to_responses(data: dict, model: str, ctx: ResponsesContext) -> dict:
    """One Anthropic message as a Responses ``response`` object."""
    seed = str(data.get("id") or "proxy")
    status, incomplete = _status(data.get("stop_reason"))
    return {
        "id": f"resp_{seed}",
        "object": "response",
        "created_at": int(time.time()),
        "status": status,
        "incomplete_details": incomplete,
        "model": model,
        "output": _output_items(data.get("content") or [], ctx, seed),
        "usage": responses_usage(data.get("usage") if isinstance(data.get("usage"), dict) else {}),
    }


def responses_error_obj(data) -> dict:
    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, dict):
        message = str(err.get("message") or "upstream error")
        kind = str(err.get("type") or "api_error")
    elif isinstance(err, str) and err:
        message, kind = err, "api_error"
    else:
        message, kind = "upstream error", "api_error"
    return {"error": {"message": message, "type": kind, "code": kind}}


def responses_error_bytes(payload: bytes) -> bytes:
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        data = {"error": payload.decode("utf-8", "replace")[:500] or "upstream error"}
    return json.dumps(responses_error_obj(data)).encode("utf-8")


def responses_body_bytes(payload: bytes, model: str, ctx: ResponsesContext) -> bytes:
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return responses_error_bytes(payload)
    if not isinstance(data, dict) or "error" in data or data.get("type") == "error":
        return responses_error_bytes(payload)
    return json.dumps(anthropic_message_to_responses(data, model, ctx)).encode("utf-8")


def _split_sse(buf: bytes) -> tuple[bytes, list[bytes]]:
    events = []
    while True:
        cut = None
        for marker in (b"\r\n\r\n", b"\n\n"):
            index = buf.find(marker)
            if index != -1 and (cut is None or index < cut[0]):
                cut = (index, marker)
        if cut is None:
            return buf, events
        index, marker = cut
        block, buf = buf[:index], buf[index + len(marker):]
        lines = [line[5:].lstrip() for line in block.splitlines() if line.startswith(b"data:")]
        if lines:
            events.append(b"\n".join(lines).strip())


@dataclass
class _Block:
    kind: str
    output_index: int
    item_id: str
    text: list = field(default_factory=list)
    json_parts: list = field(default_factory=list)
    raw: dict = field(default_factory=dict)


class ResponsesStream:
    """Anthropic SSE in, Responses SSE out.

    Text deltas stream as ``response.output_text.delta`` and tool arguments
    as ``response.function_call_arguments.delta``. Every item is announced
    with ``response.output_item.added`` and closed with
    ``response.output_item.done``. Consecutive thinking blocks become one
    ``reasoning`` item, emitted when the next non-thinking block starts or the
    message ends. The stream ends with ``response.completed`` (or
    ``response.incomplete``) carrying the full output and usage.
    """

    def __init__(self, model: str, ctx: ResponsesContext):
        self.model = model
        self.ctx = ctx
        self.buf = b""
        self.seq = 0
        self.response_id = "resp_proxy"
        self.seed = "proxy"
        self.created = int(time.time())
        self.started = False
        self.done = False
        self.blocks: dict[int, _Block] = {}
        self.items: list = []
        self.pending_thinking: list = []
        self.usage_parts: list = []
        self.stop_reason = None

    # public ---------------------------------------------------------------
    def feed(self, chunk: bytes) -> list[bytes]:
        self.buf += chunk
        self.buf, events = _split_sse(self.buf)
        out: list[bytes] = []
        for data in events:
            out.extend(self._data(data))
        return out

    def finish(self) -> list[bytes]:
        out: list[bytes] = []
        if self.buf.strip():
            out.extend(self.feed(b"\n\n"))
        if not self.done:
            out.extend(self._complete())
        return out

    def fail(self, message: str) -> list[bytes]:
        if self.done:
            return []
        self.done = True
        out = self._ensure_started()
        response = self._response("failed")
        response["error"] = {"code": "server_error", "message": message}
        out.append(self._event("response.failed", {"response": response}))
        return out

    # internals ------------------------------------------------------------
    def _event(self, kind: str, body: dict) -> bytes:
        payload = {"type": kind, "sequence_number": self.seq, **body}
        self.seq += 1
        return f"event: {kind}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n".encode("utf-8")

    def _response(self, status: str) -> dict:
        resp_status, incomplete = _status(self.stop_reason)
        if status == "final":
            status = resp_status
        return {
            "id": self.response_id,
            "object": "response",
            "created_at": self.created,
            "status": status,
            "incomplete_details": incomplete if status == "incomplete" else None,
            "model": self.model,
            "output": [item for item in self.items if item is not None],
            "usage": responses_usage(_merge_usage(self.usage_parts)) if status != "in_progress" else None,
        }

    def _ensure_started(self) -> list[bytes]:
        if self.started:
            return []
        self.started = True
        return [
            self._event("response.created", {"response": self._response("in_progress")}),
            self._event("response.in_progress", {"response": self._response("in_progress")}),
        ]

    def _flush_thinking(self) -> list[bytes]:
        if not self.pending_thinking:
            return []
        blocks = list(self.pending_thinking)
        self.pending_thinking.clear()
        index = len(self.items)
        item = {
            "type": "reasoning",
            "id": _item_id("rs", self.seed, index),
            "summary": [
                {"type": "summary_text", "text": b.get("thinking") or ""}
                for b in blocks if b.get("type") == "thinking" and b.get("thinking")
            ],
            "encrypted_content": encode_reasoning(blocks),
        }
        self.items.append(item)
        added = dict(item, summary=[])
        added.pop("encrypted_content", None)
        return [
            self._event("response.output_item.added", {"output_index": index, "item": added}),
            self._event("response.output_item.done", {"output_index": index, "item": item}),
        ]

    def _complete(self) -> list[bytes]:
        out = self._ensure_started()
        out.extend(self._flush_thinking())
        self.done = True
        response = self._response("final")
        kind = "response.incomplete" if response["status"] == "incomplete" else "response.completed"
        out.append(self._event(kind, {"response": response}))
        return out

    def _data(self, data: bytes) -> list[bytes]:
        if not data or data == b"[DONE]":
            return []
        try:
            obj = json.loads(data)
        except json.JSONDecodeError:
            return []
        if not isinstance(obj, dict):
            return []
        kind = obj.get("type")
        if kind == "message_start":
            message = obj.get("message") if isinstance(obj.get("message"), dict) else {}
            if isinstance(message.get("id"), str) and message["id"]:
                self.seed = message["id"]
                self.response_id = f"resp_{message['id']}"
            if isinstance(message.get("usage"), dict):
                self.usage_parts.append(message["usage"])
            return self._ensure_started()
        if kind == "content_block_start":
            return self._block_start(obj)
        if kind == "content_block_delta":
            return self._block_delta(obj)
        if kind == "content_block_stop":
            return self._block_stop(obj)
        if kind == "message_delta":
            if isinstance(obj.get("usage"), dict):
                self.usage_parts.append(obj["usage"])
            delta = obj.get("delta") if isinstance(obj.get("delta"), dict) else {}
            if delta.get("stop_reason"):
                self.stop_reason = delta["stop_reason"]
            return []
        if kind == "message_stop":
            return [] if self.done else self._complete()
        if kind == "error":
            err = obj.get("error") if isinstance(obj.get("error"), dict) else {}
            return self.fail(str(err.get("message") or "upstream error"))
        return []

    def _block_start(self, obj: dict) -> list[bytes]:
        out = self._ensure_started()
        index = obj.get("index")
        block = obj.get("content_block") if isinstance(obj.get("content_block"), dict) else {}
        btype = block.get("type")
        if btype in {"thinking", "redacted_thinking"}:
            self.blocks[index] = _Block(btype, -1, "", raw=dict(block))
            return out
        out.extend(self._flush_thinking())
        output_index = len(self.items)
        if btype == "text":
            item_id = _item_id("msg", self.seed, output_index)
            state = _Block("text", output_index, item_id)
            self.items.append(None)  # placeholder until done
            self.blocks[index] = state
            out.append(self._event("response.output_item.added", {
                "output_index": output_index,
                "item": {"type": "message", "id": item_id, "role": "assistant",
                         "status": "in_progress", "content": []},
            }))
            out.append(self._event("response.content_part.added", {
                "item_id": item_id, "output_index": output_index, "content_index": 0,
                "part": {"type": "output_text", "text": "", "annotations": []},
            }))
            return out
        if btype == "tool_use":
            item_id = _item_id("fc", self.seed, output_index)
            state = _Block("tool_use", output_index, item_id, raw=dict(block))
            self.items.append(None)
            self.blocks[index] = state
            stub = tool_item({**block, "input": {}}, self.ctx, item_id)
            stub["status"] = "in_progress"
            if stub["type"] == "function_call":
                stub["arguments"] = ""
            else:
                stub["input"] = ""
            out.append(self._event("response.output_item.added", {
                "output_index": output_index, "item": stub,
            }))
            return out
        return out

    def _block_delta(self, obj: dict) -> list[bytes]:
        state = self.blocks.get(obj.get("index"))
        delta = obj.get("delta") if isinstance(obj.get("delta"), dict) else {}
        if state is None:
            return []
        dtype = delta.get("type")
        if state.kind == "text" and dtype == "text_delta":
            text = delta.get("text") or ""
            state.text.append(text)
            return [self._event("response.output_text.delta", {
                "item_id": state.item_id, "output_index": state.output_index,
                "content_index": 0, "delta": text,
            })] if text else []
        if state.kind == "tool_use" and dtype == "input_json_delta":
            part = delta.get("partial_json") or ""
            state.json_parts.append(part)
            if part and state.raw.get("name") not in self.ctx.custom_tools:
                return [self._event("response.function_call_arguments.delta", {
                    "item_id": state.item_id, "output_index": state.output_index, "delta": part,
                })]
            return []
        if state.kind == "thinking":
            if dtype == "thinking_delta":
                state.raw["thinking"] = (state.raw.get("thinking") or "") + (delta.get("thinking") or "")
            elif dtype == "signature_delta":
                state.raw["signature"] = (state.raw.get("signature") or "") + (delta.get("signature") or "")
        return []

    def _block_stop(self, obj: dict) -> list[bytes]:
        state = self.blocks.pop(obj.get("index"), None)
        if state is None:
            return []
        if state.kind in {"thinking", "redacted_thinking"}:
            self.pending_thinking.append(state.raw)
            return []
        if state.kind == "text":
            text = "".join(state.text)
            item = {
                "type": "message", "id": state.item_id, "role": "assistant", "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
            self.items[state.output_index] = item
            return [
                self._event("response.output_text.done", {
                    "item_id": state.item_id, "output_index": state.output_index,
                    "content_index": 0, "text": text,
                }),
                self._event("response.content_part.done", {
                    "item_id": state.item_id, "output_index": state.output_index, "content_index": 0,
                    "part": {"type": "output_text", "text": text, "annotations": []},
                }),
                self._event("response.output_item.done", {
                    "output_index": state.output_index, "item": item,
                }),
            ]
        joined = "".join(state.json_parts)
        try:
            arguments = json.loads(joined) if joined.strip() else (state.raw.get("input") or {})
        except json.JSONDecodeError:
            arguments = {"_raw": joined}
        if not isinstance(arguments, dict):
            arguments = {"_raw": arguments}
        item = tool_item({**state.raw, "input": arguments}, self.ctx, state.item_id)
        self.items[state.output_index] = item
        out = []
        if item["type"] == "function_call":
            out.append(self._event("response.function_call_arguments.done", {
                "item_id": state.item_id, "output_index": state.output_index,
                "arguments": item["arguments"],
            }))
        out.append(self._event("response.output_item.done", {
            "output_index": state.output_index, "item": item,
        }))
        return out
