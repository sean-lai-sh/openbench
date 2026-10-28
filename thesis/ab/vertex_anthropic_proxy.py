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
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from obench.proxy import extract_usage

ANTHROPIC_VERSION = "vertex-2023-10-16"
MODEL_ID = "claude-opus-5-5"
LOCATION = "global"
# Opt-in. Unset, every call uses the model passed to start_proxy (--vertex-model).
ROUTE_BY_REQUEST_ENV = "OBENCH_VERTEX_ROUTE_BY_REQUEST"
CALL_ROLE_HEADER = "X-OB-Call-Role"
# Title and summary side calls are short next to the agent loop's 128k budget.
SHORT_CALL_MAX_TOKENS = 1024
# OpenAI chat requests omit max_tokens. Vertex requires one.
_OPENAI_DEFAULT_MAX_TOKENS = 8192
VERTEX_CLAUDE_MODELS = {
    "claude-opus-5-5": "claude-opus-5-5",
    "claude-sonnet-5-5": "claude-sonnet-5-5",
}
_SIDE_DETAILS = frozenset({"title", "summary", "helper", "memory", "subagent"})
_SPLIT_FIELDS = (
    ("input_uncached", "tokens_proxy_input_uncached"),
    ("output", "tokens_proxy_output"),
    ("cache_read", "tokens_proxy_cache_read"),
    ("cache_write", "tokens_proxy_cache_write"),
)
_TITLE_RE = re.compile(
    r"\b(title generator|generate (?:a |the )?(?:short |concise |brief )?"
    r"(?:session |conversation )?title|session title|conversation title)\b",
    re.IGNORECASE,
)
_SUMMARY_RE = re.compile(
    r"\b(summarize (?:the )?(?:conversation|session|chat|above)|"
    r"write a (?:brief |short )?summary|conversation summary|session summary)\b",
    re.IGNORECASE,
)
_MEMORY_RE = re.compile(
    r"\b(extract (?:the )?(?:relevant )?memories|memory update|"
    r"update (?:your )?memory|remember this for later)\b",
    re.IGNORECASE,
)
_HELPER_RE = re.compile(
    r"\b(helper model|utility model|side call|you are a helper)\b",
    re.IGNORECASE,
)
_SUBAGENT_RE = re.compile(
    r"\b(you are a sub-?agent|sub-?agent session|as a sub-?agent)\b",
    re.IGNORECASE,
)
_FORWARDED = ("anthropic-beta", "anthropic-version")
_LEDGER_LOCK = threading.Lock()
_DISCONNECT = (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, TimeoutError)
_NEUTRAL_USER_AGENT = "openbench"
_CC_BETAS = ("claude-code-20250219", "oauth-2025-04-20")
_CC_BETA_SET = frozenset(_CC_BETAS)
_SDK_IDENTITY = "You are a Claude agent, built on Anthropic's Claude Agent SDK."
_BILLING_RE = re.compile(
    r"^x-anthropic-billing-header:\s*"
    r"cc_version=[^;\n]*;\s*"
    r"cc_entrypoint=[^;\n]*;\s*"
    r"cch=[^;\n]*;"
)
_DROP = object()


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


def _is_identity_line(line: str) -> bool:
    text = line.strip()
    return text == _SDK_IDENTITY or text.startswith("You are Claude Code")


def _starts_with_billing(text: str) -> bool:
    return _BILLING_RE.match(text.lstrip()) is not None


def _strip_identity_text(text: str) -> tuple[str, list[str]]:
    """Drop a leading Claude Code billing header and the identity line with it."""
    removed: list[str] = []
    body = text.lstrip()
    match = _BILLING_RE.match(body)
    if match is None:
        return text, removed
    removed.append("system-billing-header")
    rest = body[match.end():]
    if rest.startswith("\r\n"):
        rest = rest[2:]
    elif rest.startswith("\n") or rest.startswith("\r"):
        rest = rest[1:]
    kept: list[str] = []
    saw_identity = False
    for line in rest.splitlines():
        if _is_identity_line(line):
            saw_identity = True
            continue
        kept.append(line)
    if saw_identity:
        removed.append("identity-line")
    return "\n".join(kept).lstrip("\n"), removed


def _identity_only(text: str) -> bool:
    lines = [line for line in text.splitlines() if line.strip()]
    return bool(lines) and all(_is_identity_line(line) for line in lines)


def _strip_leading_identity(text: str) -> tuple[str, bool]:
    lines = text.splitlines()
    index = 0
    saw = False
    while index < len(lines):
        if not lines[index].strip():
            if saw:
                index += 1
                break
            index += 1
            continue
        if _is_identity_line(lines[index]):
            saw = True
            index += 1
            continue
        break
    if not saw:
        return text, False
    return "\n".join(lines[index:]).lstrip("\n"), True


def _block_text(block) -> str | None:
    if isinstance(block, str):
        return block
    if isinstance(block, dict) and isinstance(block.get("text"), str):
        return block["text"]
    return None


def _set_block_text(block, text: str):
    if isinstance(block, str):
        return text
    block["text"] = text
    return block


def _strip_system(data: dict, removed: list[str]) -> None:
    system = data.get("system")
    if isinstance(system, str):
        if not _starts_with_billing(system):
            return
        text, parts = _strip_identity_text(system)
        removed.extend(parts)
        if text.strip():
            data["system"] = text
        else:
            data.pop("system", None)
        return
    if not isinstance(system, list) or not system:
        return
    text = _block_text(system[0])
    if text is None or not _starts_with_billing(text):
        return
    updated, parts = _strip_identity_text(text)
    removed.extend(parts)
    if updated.strip():
        system[0] = _set_block_text(system[0], updated)
    else:
        system.pop(0)
    if system and "identity-line" not in parts:
        follow = _block_text(system[0])
        if follow is not None:
            if _identity_only(follow):
                system.pop(0)
                removed.append("identity-line")
            else:
                trimmed, saw = _strip_leading_identity(follow)
                if saw:
                    removed.append("identity-line")
                    if trimmed.strip():
                        system[0] = _set_block_text(system[0], trimmed)
                    else:
                        system.pop(0)
    if not system:
        data.pop("system", None)


def _beta_parts(text: str) -> list[str] | None:
    parts = [part.strip() for part in text.split(",")]
    if len(parts) < 2:
        return None
    if all(re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in parts):
        return parts
    return None


def _strip_beta_node(node, removed: list[str]):
    if isinstance(node, dict):
        for key in list(node):
            updated = _strip_beta_node(node[key], removed)
            if updated is _DROP:
                node.pop(key, None)
            else:
                node[key] = updated
        return node
    if isinstance(node, list):
        kept = []
        for item in node:
            if isinstance(item, str) and item in _CC_BETA_SET:
                removed.append(f"beta:{item}")
                continue
            updated = _strip_beta_node(item, removed)
            if updated is not _DROP:
                kept.append(updated)
        return kept
    if isinstance(node, str):
        if node in _CC_BETA_SET:
            removed.append(f"beta:{node}")
            return _DROP
        parts = _beta_parts(node)
        if parts is not None and any(part in _CC_BETA_SET for part in parts):
            for part in parts:
                if part in _CC_BETA_SET:
                    removed.append(f"beta:{part}")
            return ",".join(part for part in parts if part not in _CC_BETA_SET)
    return node


def strip_cc_body(data: dict) -> list[str]:
    """Remove Claude Code identity that is actually present. Other fields stay.

    This is a safety net for builds that still attach the billing block. A
    request that already opted out (``auth: apiKey``) yields an empty list.
    The object is mutated. The returned labels are the parts dropped from the
    body. ``cc_identity_record`` files ``metadata.user_id`` under ``normalized``.
    """
    removed: list[str] = []
    _strip_system(data, removed)
    metadata = data.get("metadata")
    if isinstance(metadata, dict) and "user_id" in metadata:
        metadata.pop("user_id", None)
        removed.append("metadata.user_id")
        if not metadata:
            data.pop("metadata", None)
    _strip_beta_node(data, removed)
    return removed


def strip_beta_query(path: str) -> tuple[str, list[str]]:
    """Drop ``beta=true`` from a request target. Other query pairs stay."""
    if "?" not in path:
        return path, []
    route, query = path.split("?", 1)
    pairs = urllib.parse.parse_qsl(query, keep_blank_values=True)
    kept = []
    removed = False
    for key, value in pairs:
        if key == "beta" and value == "true":
            removed = True
            continue
        kept.append((key, value))
    if not removed:
        return path, []
    if not kept:
        return route, ["query:beta"]
    return route + "?" + urllib.parse.urlencode(kept), ["query:beta"]


def strip_cc_headers(headers) -> tuple[str | None, list[str]]:
    """Return the forwarded ``anthropic-beta`` value and identity labels.

    ``None`` means the client did not send the header. An empty string means
    every beta on it was a Claude Code beta, so the header is not forwarded.
    ``Authorization: Bearer proxy`` is recorded as normalized, not removed.
    ``User-Agent: claude-cli/<ver>`` is a Claude Code identity label. The
    caller sends normal auth and a neutral user agent either way.
    """
    removed: list[str] = []
    beta = headers.get("anthropic-beta")
    forwarded = None
    if beta:
        parts = [part.strip() for part in beta.split(",") if part.strip()]
        kept = []
        for part in parts:
            if part in _CC_BETA_SET:
                removed.append(f"beta:{part}")
            else:
                kept.append(part)
        forwarded = ",".join(kept)
    user_agent = headers.get("User-Agent") or ""
    if re.match(r"claude-cli/\S+", user_agent.strip()):
        removed.append("user-agent")
    authorization = headers.get("Authorization") or ""
    if authorization.strip().lower() == "bearer proxy":
        removed.append("authorization")
    return forwarded, removed


_NORMALIZED_LABELS = frozenset({"metadata.user_id", "authorization"})
_THINKING_MODES = frozenset({"default", "adaptive", "off"})
_THINKING_SENT = frozenset({"none", "enabled+budget_tokens", "adaptive"})


def classify_thinking(data) -> str:
    """What the request's ``thinking`` field actually sent.

    ``none`` when the field is absent. ``enabled+budget_tokens`` when
    ``type`` is ``enabled`` and ``budget_tokens`` is set. ``adaptive`` when
    ``type`` is ``adaptive``.
    """
    if not isinstance(data, dict):
        return "none"
    thinking = data.get("thinking")
    if not isinstance(thinking, dict):
        return "none"
    kind = thinking.get("type")
    if kind == "adaptive":
        return "adaptive"
    if kind == "enabled" and "budget_tokens" in thinking:
        return "enabled+budget_tokens"
    return "none"


BLOCK_BINDING_ENV = "OBENCH_THINKING_BLOCK_BINDING"
BLOCK_BINDING_BETA = "thinking-binding-controls-2026-08-01"


def apply_block_binding(data) -> str | None:
    """Opt-in: tell the upstream to drop thinking blocks whose prefix changed.

    Sonnet 5.5 rejects a replayed ``thinking`` block when the content before it
    was rewritten (OpenCode compaction/prune does this; PR 4838's taskflow at
    context=72000 hit it on 57/60 cells). With ``OBENCH_THINKING_BLOCK_BINDING
    =drop_block`` and at least one thinking block in ``messages``, this sets
    ``thinking.block_binding.prefix_mismatch_behavior=drop_block`` (an absent
    ``thinking`` field becomes ``{"type": "adaptive"}``). Returns the mode
    applied, or None. Off by default.
    """
    mode = os.environ.get(BLOCK_BINDING_ENV, "").strip()
    if mode != "drop_block" or not isinstance(data, dict):
        return None
    has_thinking = any(
        isinstance(block, dict) and block.get("type") in ("thinking", "redacted_thinking")
        for message in (data.get("messages") or []) if isinstance(message, dict)
        for block in (message.get("content") if isinstance(message.get("content"), list) else [])
    )
    if not has_thinking:
        return None
    thinking = data.get("thinking")
    if not isinstance(thinking, dict):
        thinking = {"type": "adaptive"}
    thinking["block_binding"] = {"prefix_mismatch_behavior": mode}
    data["thinking"] = thinking
    return mode
# Upstream models that reject sampling params OpenCode still sends. Sonnet 5.5
# on Vertex answers 400 "`temperature` is deprecated for this model"; newer
# OpenCode trees (step 3: PR 11731 onward) send it on every request.
# Opus 5.5 on Vertex gives the same 400 since 2026-10-17 (step-6 13331 smoke,
# both sides infra on the title/summary request), so it is stripped and
# recorded the same way.
DEPRECATED_SAMPLING_PARAMS = {
    "claude-sonnet-5-5": ("temperature", "top_p", "top_k"),
    "claude-opus-5-5": ("temperature", "top_p", "top_k"),
}


def strip_deprecated_sampling(data, model: str) -> list[str]:
    """Drop sampling params the upstream model rejects. Returns labels removed."""
    if not isinstance(data, dict):
        return []
    removed = []
    for name in DEPRECATED_SAMPLING_PARAMS.get(str(model).split("@", 1)[0], ()):
        if name in data:
            data.pop(name)
            removed.append(f"param:{name}")
    return removed


def cc_identity_record(removed: list[str]) -> dict:
    """Ledger value for Claude Code identity handling.

    ``removed`` lists identity parts that were stripped. ``normalized`` lists
    ``metadata.user_id`` and ``Authorization: Bearer proxy``, which are not
    Claude Code identity. ``stripped`` is true only when ``removed`` is
    non-empty.
    """
    identity: list[str] = []
    normalized: list[str] = []
    for label in removed:
        bucket = normalized if label in _NORMALIZED_LABELS else identity
        if label not in bucket:
            bucket.append(label)
    return {"stripped": bool(identity), "removed": identity, "normalized": normalized}


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


def cell_faults_path(directory: Path, cell_id: str) -> Path:
    """Sibling of the usage ledger. One JSONL row per injected fault."""
    ledger = cell_ledger_path(Path(directory), cell_id)
    return ledger.with_name(f"{ledger.stem}.faults.jsonl")


def faults_served(directory: Path | str, cell_id: str) -> int:
    path = cell_faults_path(Path(directory), cell_id)
    if not path.is_file():
        return 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    return sum(1 for line in lines if line.strip())


def _append_fault(directory: Path, cell_id: str, row: dict) -> None:
    path = cell_faults_path(Path(directory), cell_id)
    line = json.dumps(row, sort_keys=True) + "\n"
    with _LEDGER_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())


def _fault_status(kind: str) -> int:
    if kind == "http-529":
        return 529
    if kind == "http-429":
        return 429
    return 200


def _request_audience(raw: bytes) -> str:
    if b"subagent" in raw.lower():
        return "subagent"
    return "main-loop"


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


def _error_body(payload: bytes | str) -> str:
    if isinstance(payload, bytes):
        text = payload.decode("utf-8", errors="replace")
    else:
        text = str(payload)
    return text[:500]


def _append_ledger(
    directory: Path,
    cell_id: str,
    usage: dict | None,
    *,
    status: int | None = None,
    error: str | None = None,
    identity: dict | None = None,
    thinking_mode: str = "default",
    thinking_sent: str = "none",
    upstream_model: str | None = None,
    call_role: dict | None = None,
) -> None:
    path = cell_ledger_path(Path(directory), cell_id)
    row: dict = {"record_type": "request"}
    if isinstance(usage, dict):
        kept, timing = trim_ledger_usage(usage)
        row["usage"] = kept
        row.update(timing)
        # Same split the cell score uses. Sibling fields, so ``usage`` stays
        # the provider object ``proxy_split_from_usage`` already reads.
        for key, value in normalized_usage(kept).items():
            row[key] = value
    if isinstance(status, int) and not isinstance(status, bool):
        row["status"] = int(status)
    if isinstance(error, str) and error:
        row["error"] = error[:500]
    if isinstance(identity, dict):
        row["cc_identity_stripped"] = identity
    row["thinking_mode"] = thinking_mode if thinking_mode in _THINKING_MODES else "default"
    row["thinking_sent"] = thinking_sent if thinking_sent in _THINKING_SENT else "none"
    if isinstance(upstream_model, str) and upstream_model:
        row["upstream_model"] = upstream_model
    if isinstance(call_role, dict) and call_role.get("call_role") in {"main", "side"}:
        row["call_role"] = call_role["call_role"]
        detail = call_role.get("call_role_detail")
        if detail in _SIDE_DETAILS:
            row["call_role_detail"] = detail
        reason = call_role.get("call_role_reason")
        if isinstance(reason, str) and reason:
            row["call_role_reason"] = reason
    line = json.dumps(row, sort_keys=True) + "\n"
    with _LEDGER_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        _write_call_totals(Path(directory), cell_id)


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
        if self._use_metadata():
            try:
                return _metadata_token(self._now)
            except ProxyError as exc:
                if self.path is None and adc_credentials_path() is None:
                    raise ProxyError(
                        "no application_default_credentials.json; "
                        f"metadata-server ADC failed ({exc}). "
                        "Set GOOGLE_APPLICATION_CREDENTIALS to an ADC file, or run "
                        "where the GCE metadata server is reachable."
                    ) from exc
                raise
        path = self._adc_path()
        if not path.is_file():
            raise ProxyError(
                f"ADC file is missing ({path}) and OBENCH_ADC_METADATA=0 "
                "disables the metadata server. Provide the file or unset "
                "OBENCH_ADC_METADATA."
            )
        try:
            info = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ProxyError(f"cannot read ADC file {path}: {exc}") from exc
        kind = info.get("type")
        if kind == "authorized_user":
            return _refresh_authorized_user(info, self._now)
        if kind == "service_account":
            return _refresh_service_account(info, self._now)
        raise ProxyError(f"unsupported ADC type {kind!r}")

    def _use_metadata(self) -> bool:
        """File ADC when it exists. Otherwise the GCE metadata server.

        ``OBENCH_ADC_METADATA=1`` forces the metadata server. ``=0`` forces
        the file and fails before a cell when that file is absent.
        """
        if self.path is not None:
            return False
        flag = os.environ.get("OBENCH_ADC_METADATA", "").strip()
        if flag == "1":
            return True
        if flag == "0":
            return False
        return adc_credentials_path() is None

    def _adc_path(self) -> Path:
        if self.path is not None:
            return self.path
        env = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
        if env:
            return Path(env)
        return Path.home() / ".config" / "gcloud" / "application_default_credentials.json"


def adc_credentials_path() -> Path | None:
    """Existing ADC file, or None when the cell must use the metadata server."""
    env = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if env:
        path = Path(env)
        return path if path.is_file() else None
    path = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
    return path if path.is_file() else None


def _metadata_token(now) -> tuple[str, float]:
    """GCE metadata-server token for the VM's service account.

    Used when ``OBENCH_ADC_METADATA=1`` or when no ADC file exists. A docker
    bridge cell on the VM has no ``application_default_credentials.json``.
    """
    request = urllib.request.Request(
        "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
        headers={"Metadata-Flavor": "Google"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.load(response)
    except urllib.error.URLError as exc:
        raise ProxyError(f"metadata token fetch failed: {exc}") from exc
    token = payload.get("access_token")
    if not token:
        raise ProxyError("metadata server returned no access_token")
    return token, now() + int(payload.get("expires_in") or 300)


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


def _chat_route(route: str) -> bool:
    path = route.split("?", 1)[0].rstrip("/")
    return path.endswith("/chat/completions")


def _route_by_request_default() -> bool:
    flag = os.environ.get(ROUTE_BY_REQUEST_ENV, "").strip().lower()
    return flag in {"1", "true", "yes", "on"}


def normalize_vertex_model(model: str | None) -> str | None:
    """Map a harness model id onto ``claude-sonnet-5-5`` or ``claude-opus-5-5``.

    A provider prefix (``anthropic/``, ``openai/``) and an ``@default`` suffix
    are ignored. Any other id returns None.
    """
    if not isinstance(model, str):
        return None
    text = model.strip()
    if not text:
        return None
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    text = text.split("@", 1)[0].strip()
    return VERTEX_CLAUDE_MODELS.get(text)


def resolve_upstream_model(requested, configured: str, *, route_by_request: bool) -> str:
    """Vertex model for this call.

    With request routing off (the OpenCode default), ``configured`` wins even
    when the body names the other Claude model. That is ``--vertex-model``.
    With routing on, a known request model selects Sonnet or Opus and anything
    else still uses ``configured``.
    """
    if route_by_request:
        known = normalize_vertex_model(requested if isinstance(requested, str) else None)
        if known:
            return known
    return normalize_vertex_model(configured) or configured


def normalized_usage(usage: dict) -> dict:
    """Provider usage as ``input_uncached``, ``output``, ``cache_read``, ``cache_write``.

    The numbers come from ``obench.run.proxy_split_from_usage``, which is the
    cell score. A missing bucket is omitted rather than stored as zero.
    """
    if not isinstance(usage, dict) or not usage:
        return {}
    from obench.run import proxy_split_from_usage
    split = proxy_split_from_usage(usage)
    out = {}
    for name, source in _SPLIT_FIELDS:
        value = split.get(source)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        out[name] = int(value)
    return out


def _prompt_text(data: dict, *, system_only: bool) -> str:
    if system_only:
        return _system_text(data)
    parts = [_system_text(data)]
    messages = data.get("messages")
    if isinstance(messages, list):
        for message in messages[:6]:
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                for block in content[:8]:
                    if isinstance(block, str):
                        parts.append(block)
                    elif isinstance(block, dict) and isinstance(block.get("text"), str):
                        parts.append(block["text"])
    return "\n".join(parts)


def _request_has_tools(data: dict) -> bool:
    tools = data.get("tools")
    if isinstance(tools, list) and tools:
        return True
    functions = data.get("functions")
    return isinstance(functions, list) and bool(functions)


def _request_max_tokens(data: dict):
    for key in ("max_tokens", "max_completion_tokens", "max_output_tokens"):
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        return value
    return None


def _role(role: str, reason: str, detail: str | None = None) -> dict:
    out = {"call_role": role, "call_role_reason": reason}
    if detail:
        out["call_role_detail"] = detail
    return out


def parse_call_role_header(value: str | None) -> dict | None:
    """``X-OB-Call-Role`` when it names a role this proxy records.

    Accepted values are ``main``, ``side``, a side detail (``title``,
    ``summary``, ``helper``, ``memory``, ``subagent``), and ``side:<detail>``.
    Anything else returns None so the heuristic can run.
    """
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if text == "main":
        return _role("main", "header")
    if text == "side":
        return _role("side", "header")
    detail = text.split(":", 1)[1].strip() if text.startswith("side:") else text
    if detail in _SIDE_DETAILS and (text == detail or text.startswith("side:")):
        return _role("side", "header", detail)
    return None


def classify_call_role(data, header: str | None) -> dict:
    """Tag one model call ``main`` or ``side``.

    The header wins. Otherwise a subagent prompt is ``side`` / ``subagent``
    even when it carries tools. Title and summary need all three of: no
    tools, ``max_tokens`` at most ``SHORT_CALL_MAX_TOKENS``, and a matching
    system prompt. Memory and helper prompts are tagged when the wording is
    specific. A short call with no tools and no matching prompt is ``side``
    with reason ``heuristic:short-no-tools``. Everything else is ``main``.
    """
    parsed = parse_call_role_header(header)
    if parsed is not None:
        return parsed
    if not isinstance(data, dict):
        return _role("main", "heuristic:main")
    if _SUBAGENT_RE.search(_prompt_text(data, system_only=False)):
        return _role("side", "heuristic:subagent", "subagent")
    system = _system_text(data)
    tools = _request_has_tools(data)
    max_tokens = _request_max_tokens(data)
    short = (
        isinstance(max_tokens, (int, float))
        and not isinstance(max_tokens, bool)
        and max_tokens <= SHORT_CALL_MAX_TOKENS
    )
    if not tools and _MEMORY_RE.search(system):
        return _role("side", "heuristic:memory", "memory")
    if not tools and _HELPER_RE.search(system):
        return _role("side", "heuristic:helper", "helper")
    if not tools and short:
        if _TITLE_RE.search(system):
            return _role("side", "heuristic:title", "title")
        if _SUMMARY_RE.search(system):
            return _role("side", "heuristic:summary", "summary")
        return _role("side", "heuristic:short-no-tools")
    return _role("main", "heuristic:main")


def _content_blocks(content) -> list:
    if content is None:
        return []
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    if not isinstance(content, list):
        return [{"type": "text", "text": str(content)}]
    blocks = []
    for part in content:
        if isinstance(part, str):
            if part:
                blocks.append({"type": "text", "text": part})
            continue
        if not isinstance(part, dict):
            continue
        kind = part.get("type") or "text"
        if kind == "text":
            block = {"type": "text", "text": part.get("text") or ""}
            if "cache_control" in part:
                block["cache_control"] = part["cache_control"]
            blocks.append(block)
        elif kind == "image_url":
            image = _image_block(part)
            if image is not None:
                blocks.append(image)
        else:
            blocks.append(dict(part))
    return blocks


def _image_block(part: dict) -> dict | None:
    image = part.get("image_url")
    url = image.get("url") if isinstance(image, dict) else image
    if not isinstance(url, str) or not url:
        return None
    if url.startswith("data:"):
        header, _, data = url.partition(",")
        media = header[5:].split(";", 1)[0] if header.startswith("data:") else ""
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media or "image/png",
                "data": data,
            },
        }
    return {"type": "image", "source": {"type": "url", "url": url}}


def _message_content(content):
    if isinstance(content, str) or content is None:
        return content or ""
    blocks = _content_blocks(content)
    if len(blocks) == 1 and blocks[0].get("type") == "text" and "cache_control" not in blocks[0]:
        return blocks[0]["text"]
    return blocks


def _concat_content(left, right):
    def blocks(value):
        if isinstance(value, str):
            return [{"type": "text", "text": value}] if value else []
        if isinstance(value, list):
            return list(value)
        return [{"type": "text", "text": str(value)}] if value else []
    return blocks(left) + blocks(right)


def _merge_messages(messages: list) -> list:
    merged = []
    for message in messages:
        if merged and merged[-1]["role"] == message["role"]:
            merged[-1]["content"] = _concat_content(merged[-1]["content"], message["content"])
        else:
            merged.append(message)
    return merged


def _openai_tool(tool: dict) -> dict:
    if not isinstance(tool, dict):
        raise ProxyError("tool entries must be objects")
    if "input_schema" in tool and isinstance(tool.get("name"), str):
        return tool
    function = tool.get("function") if isinstance(tool.get("function"), dict) else tool
    converted = {
        "name": function.get("name") or "",
        "description": function.get("description") or "",
        "input_schema": function.get("parameters") or {"type": "object", "properties": {}},
    }
    cache = tool.get("cache_control", function.get("cache_control"))
    if cache is not None:
        converted["cache_control"] = cache
    return converted


def _openai_tool_choice(choice):
    if choice == "auto" or choice is None:
        return {"type": "auto"}
    if choice == "none":
        return {"type": "none"}
    if choice == "required":
        return {"type": "any"}
    if isinstance(choice, dict):
        function = choice.get("function") if isinstance(choice.get("function"), dict) else {}
        name = function.get("name") or choice.get("name")
        if isinstance(name, str) and name:
            return {"type": "tool", "name": name}
    raise ProxyError(f"unsupported tool_choice {choice!r}")


def _openai_max_tokens(data: dict) -> int:
    for key in ("max_tokens", "max_completion_tokens"):
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if value > 0:
            return int(value)
    return _OPENAI_DEFAULT_MAX_TOKENS


def _system_value(blocks: list):
    if blocks and all(set(block) <= {"type", "text"} and block.get("type") == "text" for block in blocks):
        return "\n\n".join(block.get("text") or "" for block in blocks)
    return blocks


def openai_to_anthropic(data: dict) -> dict:
    """OpenAI ``/v1/chat/completions`` body as an Anthropic Messages body.

    Tools, tool calls, tool results, and ``cache_control`` on text or tool
    blocks are kept. The model id stays so the caller can route Sonnet or
    Opus; ``translate_body`` removes it before Vertex.
    """
    if not isinstance(data, dict):
        raise ProxyError("request body must be an object")
    messages = data.get("messages")
    if messages is None:
        messages = []
    if not isinstance(messages, list):
        raise ProxyError("messages must be a list")
    system_blocks: list = []
    anth_messages: list = []
    for message in messages:
        if not isinstance(message, dict):
            raise ProxyError("each message must be an object")
        role = message.get("role")
        if role in {"system", "developer"}:
            system_blocks.extend(_content_blocks(message.get("content")))
            continue
        if role == "tool":
            anth_messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": message.get("tool_call_id") or "",
                    "content": _message_content(message.get("content")),
                }],
            })
            continue
        if role == "assistant":
            blocks = _content_blocks(message.get("content"))
            for call in message.get("tool_calls") or []:
                if not isinstance(call, dict):
                    continue
                function = call.get("function") if isinstance(call.get("function"), dict) else {}
                arguments = function.get("arguments") if function else call.get("arguments")
                if isinstance(arguments, str):
                    try:
                        parsed = json.loads(arguments) if arguments else {}
                    except json.JSONDecodeError:
                        parsed = {"_raw": arguments}
                elif isinstance(arguments, dict):
                    parsed = arguments
                else:
                    parsed = {}
                if not isinstance(parsed, dict):
                    parsed = {"_raw": parsed}
                blocks.append({
                    "type": "tool_use",
                    "id": call.get("id") or "toolu",
                    "name": function.get("name") or call.get("name") or "",
                    "input": parsed,
                })
            anth_messages.append({
                "role": "assistant",
                "content": blocks if blocks else "",
            })
            continue
        anth_messages.append({
            "role": "user",
            "content": _message_content(message.get("content")),
        })
    out: dict = {
        "messages": _merge_messages(anth_messages),
        "max_tokens": _openai_max_tokens(data),
    }
    if system_blocks:
        out["system"] = _system_value(system_blocks)
    if isinstance(data.get("model"), str):
        out["model"] = data["model"]
    if data.get("stream") is True:
        out["stream"] = True
    tools = data.get("tools")
    if isinstance(tools, list) and tools:
        out["tools"] = [_openai_tool(tool) for tool in tools]
    if "tool_choice" in data and data.get("tool_choice") is not None:
        out["tool_choice"] = _openai_tool_choice(data.get("tool_choice"))
    for key in ("temperature", "top_p", "top_k", "metadata", "thinking"):
        if key in data:
            out[key] = data[key]
    if "stop_sequences" in data:
        out["stop_sequences"] = data["stop_sequences"]
    elif "stop" in data:
        stop = data["stop"]
        if isinstance(stop, str):
            out["stop_sequences"] = [stop]
        elif isinstance(stop, list):
            out["stop_sequences"] = [item for item in stop if isinstance(item, str)]
    return out


def _int_token(value, default: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return int(value)


def _cache_write_tokens(usage: dict) -> int:
    value = usage.get("cache_creation_input_tokens")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    creation = usage.get("cache_creation")
    if not isinstance(creation, dict):
        return 0
    total = 0
    for item in creation.values():
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            continue
        total += int(item)
    return total


def openai_usage(usage: dict | None) -> dict:
    """Anthropic usage as an OpenAI ``usage`` object, with cache fields kept.

    ``prompt_tokens`` is uncached input plus cache read plus cache write.
    Anthropic's ``input_tokens`` is the uncached portion. The cache counters
    are also copied under their Anthropic names.
    """
    usage = usage if isinstance(usage, dict) else {}
    uncached = _int_token(usage.get("input_tokens"))
    output = _int_token(usage.get("output_tokens"))
    cache_read = _int_token(usage.get("cache_read_input_tokens"))
    cache_write = _cache_write_tokens(usage)
    prompt = uncached + cache_read + cache_write
    out = {
        "prompt_tokens": prompt,
        "completion_tokens": output,
        "total_tokens": prompt + output,
        "prompt_tokens_details": {
            "cached_tokens": cache_read,
            "cache_write_tokens": cache_write,
        },
        "cache_read_input_tokens": cache_read,
        "cache_creation_input_tokens": cache_write,
    }
    if isinstance(usage.get("cache_creation"), dict):
        out["cache_creation"] = usage["cache_creation"]
    return out


def _openai_finish(stop_reason) -> str:
    return {
        "end_turn": "stop",
        "stop_sequence": "stop",
        "max_tokens": "length",
        "tool_use": "tool_calls",
        "refusal": "content_filter",
    }.get(stop_reason, "stop")


def anthropic_message_to_openai(data: dict, model: str) -> dict:
    """One Anthropic message as an OpenAI chat completion."""
    content = data.get("content")
    texts: list[str] = []
    tool_calls = []
    if isinstance(content, str):
        texts.append(content)
    elif isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                texts.append(block["text"])
            elif block.get("type") == "tool_use":
                tool_calls.append({
                    "id": block.get("id") or "toolu",
                    "type": "function",
                    "function": {
                        "name": block.get("name") or "",
                        "arguments": json.dumps(block.get("input") or {}, separators=(",", ":")),
                    },
                })
    message: dict = {"role": "assistant", "content": "".join(texts) if texts else None}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "id": data.get("id") or "chatcmpl-proxy",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": message,
            "finish_reason": _openai_finish(data.get("stop_reason")),
        }],
        "usage": openai_usage(data.get("usage") if isinstance(data.get("usage"), dict) else {}),
    }


def openai_error_obj(data: dict) -> dict:
    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, dict):
        return {"error": {
            "message": str(err.get("message") or "upstream error"),
            "type": str(err.get("type") or "api_error"),
        }}
    if isinstance(err, str) and err:
        return {"error": {"message": err, "type": "api_error"}}
    return {"error": {"message": "upstream error", "type": "api_error"}}


def openai_response_bytes(payload: bytes, model: str) -> bytes:
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return payload
    if not isinstance(data, dict):
        return payload
    if "error" in data or data.get("type") == "error":
        return json.dumps(openai_error_obj(data)).encode("utf-8")
    return json.dumps(anthropic_message_to_openai(data, model)).encode("utf-8")


def openai_error_bytes(payload: bytes) -> bytes:
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return payload
    if not isinstance(data, dict):
        return payload
    return json.dumps(openai_error_obj(data)).encode("utf-8")


def _split_sse_events(buf: bytes) -> tuple[bytes, list[bytes]]:
    events = []
    while True:
        sep = None
        for marker in (b"\r\n\r\n", b"\n\n", b"\r\r"):
            index = buf.find(marker)
            if index != -1 and (sep is None or index < sep[0]):
                sep = (index, marker)
        if sep is None:
            break
        index, marker = sep
        block = buf[:index]
        buf = buf[index + len(marker):]
        data_lines = []
        for line in block.splitlines():
            if line.startswith(b"data:"):
                data_lines.append(line[5:].lstrip())
        if data_lines:
            events.append(b"\n".join(data_lines).strip())
    return buf, events


class _OpenAIStream:
    """Anthropic SSE in, OpenAI chat-completion chunks out."""

    def __init__(self, model: str):
        self.model = model
        self.buf = b""
        self.message_id = "chatcmpl-proxy"
        self.created = int(time.time())
        self.saw_role = False
        self.tool_ids: dict[int, int] = {}
        self.next_tool = 0
        self.usage_parts: list[dict] = []
        self.finish_reason: str | None = None
        self.done = False

    def feed(self, chunk: bytes) -> list[bytes]:
        self.buf += chunk
        self.buf, events = _split_sse_events(self.buf)
        out: list[bytes] = []
        for data in events:
            out.extend(self._data(data))
        return out

    def finish(self) -> list[bytes]:
        extra: list[bytes] = []
        if self.buf.strip():
            extra = self.feed(b"\n\n")
        if self.done:
            return extra
        self.done = True
        tail: list[bytes] = []
        if self.finish_reason is None:
            self.finish_reason = "stop"
            tail.append(self._chunk({}, "stop", with_usage=True))
        tail.append(b"data: [DONE]\n\n")
        return extra + tail

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
        out: list[bytes] = []
        if kind == "message_start":
            message = obj.get("message") if isinstance(obj.get("message"), dict) else {}
            if isinstance(message.get("id"), str) and message["id"]:
                self.message_id = message["id"]
            usage = message.get("usage")
            if isinstance(usage, dict):
                self.usage_parts.append(usage)
            out.extend(self._ensure_role())
            return out
        if kind == "content_block_start":
            block = obj.get("content_block") if isinstance(obj.get("content_block"), dict) else {}
            if block.get("type") != "tool_use":
                return out
            index = obj.get("index")
            tool_index = self.next_tool
            self.next_tool += 1
            if isinstance(index, int) and not isinstance(index, bool):
                self.tool_ids[index] = tool_index
            out.extend(self._ensure_role())
            out.append(self._chunk({
                "tool_calls": [{
                    "index": tool_index,
                    "id": block.get("id") or f"toolu_{tool_index}",
                    "type": "function",
                    "function": {"name": block.get("name") or "", "arguments": ""},
                }],
            }, None))
            return out
        if kind == "content_block_delta":
            delta = obj.get("delta") if isinstance(obj.get("delta"), dict) else {}
            dtype = delta.get("type")
            if dtype == "text_delta" and isinstance(delta.get("text"), str) and delta["text"]:
                out.extend(self._ensure_role())
                out.append(self._chunk({"content": delta["text"]}, None))
            elif dtype == "input_json_delta" and isinstance(delta.get("partial_json"), str):
                index = obj.get("index")
                if isinstance(index, int) and not isinstance(index, bool):
                    tool_index = self.tool_ids.get(index, 0)
                else:
                    tool_index = 0
                out.append(self._chunk({
                    "tool_calls": [{
                        "index": tool_index,
                        "function": {"arguments": delta["partial_json"]},
                    }],
                }, None))
            return out
        if kind == "message_delta":
            usage = obj.get("usage")
            if isinstance(usage, dict):
                self.usage_parts.append(usage)
            delta = obj.get("delta") if isinstance(obj.get("delta"), dict) else {}
            stop = delta.get("stop_reason")
            if isinstance(stop, str) and stop:
                self.finish_reason = _openai_finish(stop)
                out.append(self._chunk({}, self.finish_reason, with_usage=True))
            return out
        if kind == "message_stop":
            if self.finish_reason is None:
                self.finish_reason = "stop"
                out.append(self._chunk({}, "stop", with_usage=True))
            if not self.done:
                self.done = True
                out.append(b"data: [DONE]\n\n")
            return out
        usage = obj.get("usage")
        if isinstance(usage, dict):
            self.usage_parts.append(usage)
        return out

    def _ensure_role(self) -> list[bytes]:
        if self.saw_role:
            return []
        self.saw_role = True
        return [self._chunk({"role": "assistant"}, None)]

    def _chunk(self, delta: dict, finish, *, with_usage: bool = False) -> bytes:
        body = {
            "id": self.message_id,
            "object": "chat.completion.chunk",
            "created": self.created,
            "model": self.model,
            "choices": [{
                "index": 0,
                "delta": delta,
                "finish_reason": finish,
            }],
        }
        if with_usage:
            merged = merge_message_usage(self.usage_parts) or {}
            body["usage"] = openai_usage(merged)
        return b"data: " + json.dumps(body, separators=(",", ":")).encode("utf-8") + b"\n\n"


def _split_for_total(row: dict) -> dict:
    keys = ("input_uncached", "output", "cache_read", "cache_write")
    if all(
        isinstance(row.get(key), (int, float)) and not isinstance(row.get(key), bool)
        for key in keys
    ):
        return {key: int(row[key]) for key in keys}
    norm = normalized_usage(row.get("usage") if isinstance(row.get("usage"), dict) else {})
    return {key: int(norm.get(key) or 0) for key in keys}


def summarize_call_totals(rows: list) -> dict:
    """All-call and main-only totals for one cell ledger.

    ``side`` rows stay in ``all`` and stay out of ``main``. A row with no
    ``call_role`` counts as main, which is how a ledger written before
    tagging still sums.
    """
    keys = ("input_uncached", "output", "cache_read", "cache_write")

    def blank() -> dict:
        return {key: 0 for key in keys} | {"calls": 0}

    buckets = {"all": blank(), "main": blank()}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("usage"), dict):
            continue
        split = _split_for_total(row)
        buckets["all"]["calls"] += 1
        for key in keys:
            buckets["all"][key] += split[key]
        if row.get("call_role") != "side":
            buckets["main"]["calls"] += 1
            for key in keys:
                buckets["main"][key] += split[key]
    return buckets


def cell_totals_path(directory: Path, cell_id: str) -> Path:
    """Per-cell all-call and main-only totals, beside the request ledger."""
    ledger = cell_ledger_path(Path(directory), cell_id)
    return ledger.with_name(f"{ledger.stem}.totals.json")


def read_call_totals(directory: Path, cell_id: str) -> dict | None:
    path = cell_totals_path(directory, cell_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_call_totals(directory: Path, cell_id: str) -> None:
    """Rewrite ``<cell>.totals.json`` from the ledger. Caller holds the lock."""
    path = cell_ledger_path(directory, cell_id)
    rows = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    payload = json.dumps(summarize_call_totals(rows), sort_keys=True) + "\n"
    dest = cell_totals_path(directory, cell_id)
    tmp = dest.with_name(f".{dest.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, dest)


class Proxy:
    def __init__(self, httpd: ThreadingHTTPServer, thread: threading.Thread):
        self._httpd = httpd
        self._thread = thread
        self._faults: dict[str, dict] = {}
        self._fault_lock = threading.Lock()
        self._message_index: dict[str, int] = {}
        self._reached: set[str] = set()
        self._bridge = None

    def note_message(self, cell_id: str) -> int:
        """1-based index of a ``/messages`` POST for this cell."""
        with self._fault_lock:
            index = self._message_index.get(cell_id, 0) + 1
            self._message_index[cell_id] = index
            return index

    def note_reached(self, cell_id: str) -> None:
        """Record that a cell's request arrived at this listener."""
        if not cell_id:
            return
        with self._fault_lock:
            self._reached.add(cell_id)

    def reached(self, cell_id: str) -> bool:
        with self._fault_lock:
            return cell_id in self._reached

    def publish_on_docker_bridge(self):
        """Forward the loopback port on the docker bridge gateway.

        Host-network and local cells do not call this. The loopback listener
        stays the default. The forwarder refuses a wildcard bind.
        """
        from thesis.ab.proxy_bridge import BridgeError, publish_proxy_port

        if self._bridge is not None and getattr(self._bridge, "owns_socket", False):
            return self._bridge
        port = int(self._httpd.server_address[1])
        try:
            self._bridge = publish_proxy_port(port)
        except BridgeError as exc:
            raise ProxyError(str(exc)) from exc
        return self._bridge

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
        bridge = self._bridge
        self._bridge = None
        if bridge is not None:
            bridge.close()
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)


def start_proxy(project: str, *, model: str = MODEL_ID, location: str = LOCATION,
                token, upstream: str = "https://aiplatform.googleapis.com",
                ledger_dir: Path | None = None, thinking_mode: str = "default",
                route_by_request: bool | None = None) -> Proxy:
    upstream = upstream.rstrip("/")
    ledger = Path(ledger_dir) if ledger_dir is not None else None
    if thinking_mode not in _THINKING_MODES:
        thinking_mode = "default"
    if route_by_request is None:
        route_by_request = _route_by_request_default()
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
            if cell:
                holder["proxy"].note_reached(cell)
            route, query_removed = strip_beta_query(route)
            removed = list(query_removed)
            presentation = "openai" if _chat_route(route) else "anthropic"
            try:
                parsed = json.loads(raw.decode("utf-8")) if raw else None
            except (UnicodeDecodeError, json.JSONDecodeError):
                parsed = None
            requested_model = parsed.get("model") if isinstance(parsed, dict) else None
            upstream_model = resolve_upstream_model(
                requested_model, model, route_by_request=route_by_request,
            )
            call_role = classify_call_role(
                parsed if isinstance(parsed, dict) else None,
                self.headers.get(CALL_ROLE_HEADER),
            )
            if presentation == "openai":
                if not isinstance(parsed, dict):
                    payload = json.dumps({
                        "error": {
                            "message": "request body must be an object",
                            "type": "invalid_request_error",
                        },
                    }).encode("utf-8")
                    self._send(400, "application/json", payload)
                    return
                try:
                    parsed = openai_to_anthropic(parsed)
                except ProxyError as exc:
                    payload = json.dumps({
                        "error": {"message": str(exc), "type": "invalid_request_error"},
                    }).encode("utf-8")
                    self._send(400, "application/json", payload)
                    return
                raw = json.dumps(parsed).encode("utf-8")
            sampling_removed: list[str] = []
            if isinstance(parsed, dict):
                removed.extend(strip_cc_body(parsed))
                sampling_removed = strip_deprecated_sampling(parsed, upstream_model)
                raw = json.dumps(parsed).encode("utf-8")
            binding = apply_block_binding(parsed) if _message_route(route) else None
            if binding:
                raw = json.dumps(parsed).encode("utf-8")
            beta_header, header_removed = strip_cc_headers(self.headers)
            removed.extend(header_removed)
            if binding:
                parts = [p for p in (beta_header or "").split(",") if p.strip()]
                if BLOCK_BINDING_BETA not in parts:
                    parts.append(BLOCK_BINDING_BETA)
                beta_header = ",".join(parts)
            identity = cc_identity_record(removed)
            if binding:
                identity["thinking_block_binding"] = binding
            if sampling_removed:
                identity["sampling_params_removed"] = sampling_removed
            sent = classify_thinking(parsed)
            if ledger is not None and cell and length:
                note_cell_bytes(ledger, cell, length)
            message_index = None
            if cell and _message_route(route):
                message_index = holder["proxy"].note_message(cell)
            fault = holder["proxy"].take_fault(cell, route, raw)
            if fault:
                if ledger is not None and cell and message_index is not None:
                    _append_fault(ledger, cell, {
                        "audience": _request_audience(raw),
                        "request_index": message_index,
                        "status": _fault_status(fault),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                self._send_fault(fault)
                return
            try:
                kind, body = translate_body(route, raw)
                path = vertex_path(project, upstream_model, kind, location)
                if "?" in route:
                    path += route[route.index("?"):]
                bearer = token() if callable(token) else token
            except (ProxyError, OSError) as exc:
                payload = json.dumps({"error": str(exc)}).encode("utf-8")
                if presentation == "openai":
                    payload = json.dumps({
                        "error": {"message": str(exc), "type": "invalid_request_error"},
                    }).encode("utf-8")
                self._send(400, "application/json", payload)
                return
            headers = {
                "Authorization": f"Bearer {bearer}",
                "Content-Type": "application/json",
                "User-Agent": _NEUTRAL_USER_AGENT,
            }
            for name in _FORWARDED:
                if name == "anthropic-beta":
                    if beta_header:
                        headers[name] = beta_header
                    continue
                value = self.headers.get(name)
                if value:
                    headers[name] = value
            self._forward(
                upstream + path, headers, body,
                cell if ledger is not None else None, kind, identity, sent,
                presentation=presentation, call_role=call_role,
                upstream_model_id=upstream_model,
            )

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

        def _record(self, cell: str | None, usage: dict | None, status: int | None = None,
                    identity: dict | None = None, thinking_sent: str = "none",
                    call_role: dict | None = None, upstream_model_id: str | None = None) -> None:
            # One row per messages or chat-completions POST on /c/<cell-id>/.
            # A subagent or child session that reused that base URL is included
            # in the cell total. The role tag does not change that total.
            if ledger is None or not cell or not usage:
                return
            _append_ledger(
                ledger, cell, usage, status=status, identity=identity,
                thinking_mode=thinking_mode, thinking_sent=thinking_sent,
                upstream_model=upstream_model_id or model,
                call_role=call_role,
            )

        def _record_error(self, cell: str | None, status: int, payload: bytes | str,
                          identity: dict | None = None, thinking_sent: str = "none",
                          call_role: dict | None = None, upstream_model_id: str | None = None) -> None:
            if ledger is None or not cell:
                return
            _append_ledger(
                ledger, cell, None, status=status, error=_error_body(payload), identity=identity,
                thinking_mode=thinking_mode, thinking_sent=thinking_sent,
                upstream_model=upstream_model_id or model,
                call_role=call_role,
            )

        def _forward(self, url: str, headers: dict, body: bytes, cell: str | None, kind: str,
                     identity: dict | None = None, thinking_sent: str = "none",
                     presentation: str = "anthropic", call_role: dict | None = None,
                     upstream_model_id: str | None = None) -> None:
            request = urllib.request.Request(url, data=body, headers=headers, method="POST")
            response = None
            raw = bytearray()
            parts: list[dict] = []
            pending = b""
            recorded = False
            status: int | None = None
            called = upstream_model_id or model
            translate_out = presentation == "openai" and kind != "count"
            stream_tx = _OpenAIStream(called) if translate_out and kind == "stream" else None

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
                    self._record_error(
                        cell, int(exc.code), payload, identity, thinking_sent,
                        call_role, called,
                    )
                    if presentation == "openai":
                        payload = openai_error_bytes(payload)
                    content_type = exc.headers.get("Content-Type") or "application/json"
                    self._send(exc.code, content_type, payload)
                    return
                except urllib.error.URLError as exc:
                    payload = json.dumps({"error": str(exc)}).encode("utf-8")
                    self._record_error(
                        cell, 502, payload, identity, thinking_sent, call_role, called,
                    )
                    if presentation == "openai":
                        payload = openai_error_bytes(payload)
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
                    if stream_tx is not None:
                        for piece in stream_tx.feed(chunk):
                            self._write_chunk(piece)
                    elif not translate_out:
                        self._write_chunk(chunk)
                usage = finish_usage()
                if kind != "count":
                    self._record(
                        cell, usage, status, identity, thinking_sent, call_role, called,
                    )
                    recorded = True
                if stream_tx is not None:
                    for piece in stream_tx.finish():
                        self._write_chunk(piece)
                elif translate_out:
                    self._write_chunk(openai_response_bytes(bytes(raw), called))
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except _DISCONNECT:
                self.close_connection = True
                if not recorded and kind != "count":
                    self._record(
                        cell, finish_usage(), status, identity, thinking_sent, call_role, called,
                    )
            finally:
                if response is not None:
                    response.close()

        def log_message(self, fmt, *args):
            return

    # Loopback only. Bridge containers reach this port through the forwarder
    # on the docker bridge gateway (thesis/ab/proxy_bridge.py). Host-network
    # cells keep using this listener. Do not bind 0.0.0.0.
    httpd = Server(("127.0.0.1", 0), Handler)
    proxy = Proxy(httpd, None)
    holder["proxy"] = proxy
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    proxy._thread = thread
    thread.start()
    return proxy


def start_from_env(ledger_dir: Path | None = None, thinking_mode: str = "default",
                   model: str = MODEL_ID) -> Proxy:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCLOUD_PROJECT")
    if not project:
        raise ProxyError("GOOGLE_CLOUD_PROJECT is not set")
    token = AdcToken()
    # Resolve ADC before any cell. A missing file uses the metadata server.
    # A failure here does not start the agent.
    try:
        token()
    except ProxyError:
        raise
    return start_proxy(
        project, model=model, token=token, ledger_dir=ledger_dir,
        thinking_mode=thinking_mode,
    )
