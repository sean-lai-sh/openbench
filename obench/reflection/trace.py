"""Per-step traces for the reflection loop (schema: ``TRACE_SCHEMA.md``).

One OpenCode run gives two append-only records, both on disk before this
module reads them:

* OpenCode's own ``--format json --thinking`` event stream: ``step_start``,
  ``tool_use``, ``text``, ``reasoning``, ``step_finish`` (and ``error``), one
  JSON object per line. Each ``step_start``/``step_finish`` pair is one model
  round.
* One wire record per model call (``openbench.reflection.wire/v1``), written
  where the call is routed (SEA-105): the request body exactly as sent, the
  model actually served, and the provider's response ``usage`` object.
  ``wire_records_from_proxy_ledger`` builds them from the existing Vertex proxy
  ledger.

``build_trace`` joins them in order (main OpenCode step *i* is answered main
wire call *i*) into one ``openbench.reflection.step/v1`` record per main step,
and ``write_trace`` writes them as JSONL. A compaction summary is its own
step in the same session; it is not a main step, and its thinking tokens are
not added to the main total. Token counts, thinking tokens and cache tokens
come from the provider's response usage, never from OpenCode's
``tokens.reasoning``: unset thinking still returns server thinking tokens.

Failures raise ``TraceError`` with a stable ``code``; nothing is written for a
run that fails validation.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from obench.reflection.opencode import load_pin

TRACE_SCHEMA = "openbench.reflection.step/v1"
WIRE_SCHEMA = "openbench.reflection.wire/v1"
WIRES = ("anthropic", "openai_chat", "gemini")
THINKING_KINDS = ("full", "summary", "redacted", "omitted", "none")
# thinking.flag: typed notes on how the reported thinking tokens relate to the returned text.
THINKING_FLAGS = (
    "reported_zero_text_present",   # usage reports 0 thinking tokens but thinking text came back
    "reported_absent_text_present", # usage has no thinking-token field at all, but thinking text came back (gpt-oss on Vertex)
)
# OpenCode inserts this user text after a compaction summary, before the next
# model step. It is input, not a step. ``part.synthetic`` is the pin's flag;
# the prefix covers a stream that omitted the flag.
SYNTHETIC_CONTINUE_PREFIX = "Continue if you have next steps, or stop and ask for clarification if"
# A text event in the gap after compaction used to abort the parse. It is now
# counted on the trial row and the trace is still written.
IMPLICIT_TEXT_WARNING = "implicit_text_before_step_start"
ERROR_CODES = (
    "events_malformed",     # the OpenCode stream is not a sequence of steps
    "wire_malformed",       # a wire record is not a wire/v1 object
    "step_call_mismatch",   # OpenCode steps and main wire calls don't pair up
    "request_missing",      # a step's wire record has no request body
    "thinking_unset",       # the request carried no explicit thinking setting
    "usage_missing",        # the response had no usage object
    "usage_malformed",      # usage is not an object, or a counter is missing/not an int
)


class TraceError(Exception):
    """A run that can't be traced. ``code`` is one of ``ERROR_CODES``;
    ``step`` is the 1-based step it was found at, when there is one."""

    def __init__(self, code: str, message: str, step: int | None = None):
        assert code in ERROR_CODES, code
        self.code, self.step = code, step
        where = f" (step {step})" if step is not None else ""
        super().__init__(f"{code}{where}: {message}")


# ---------------------------------------------------------------- OpenCode


def parse_events(lines: Iterable[str]) -> list[dict]:
    """JSON events from an OpenCode stream or a transcript of one. Blank
    lines, ``#`` header lines and non-JSON log lines are skipped; a JSON line
    without a string ``type`` is malformed."""
    events = []
    for number, line in enumerate(lines, 1):
        text = line.strip()
        if not text.startswith("{"):
            continue
        try:
            event = json.loads(text)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise TraceError("events_malformed", f"line {number} is JSON but not an OpenCode event")
        events.append(event)
    return events


def _part(event: dict) -> dict:
    part = event.get("part")
    return part if isinstance(part, dict) else {}


def _synthetic_continue(part: dict) -> bool:
    """OpenCode's post-compaction prompt. Input, not a model step."""
    if part.get("synthetic") is True:
        return True
    text = part.get("text")
    return isinstance(text, str) and text.startswith(SYNTHETIC_CONTINUE_PREFIX)


class OpenCodeParse:
    """One event stream grouped into model steps.

    ``steps`` includes main, compaction, and (when distinguished) summary
    steps. Each step has ``kind``. Synthetic continue texts are not steps.
    ``trace_warnings`` lists non-fatal codes; one
    ``implicit_text_before_step_start`` per text recovered in the gap after
    a compaction. A text before any step, with no compaction behind it, is
    still ``events_malformed``."""

    def __init__(self, steps: list[dict], synthetic_continue_messages: int, trace_warnings: list[str]):
        self.steps = steps
        self.synthetic_continue_messages = synthetic_continue_messages
        self.trace_warnings = trace_warnings

    def by_kind(self, kind: str) -> list[dict]:
        return [step for step in self.steps if step.get("kind") == kind]


def parse_opencode(events: list[dict]) -> OpenCodeParse:
    """Group events into steps. Parts attach to the step with the same
    ``messageID`` (falling back to the open step). A step with no
    ``step_finish`` (killed run) is kept with ``finish`` None.

    The step immediately before OpenCode's synthetic continue text is a
    compaction step (``kind`` ``compaction``): OpenCode emits the compaction
    summary as a step in the same session, then that prompt. The prompt does
    not open a step. Any other text in that same gap (after the compaction
    step, before the next ``step_start``) is an implicit non-model segment:
    it is warned, not fatal. Summary steps stay ``kind`` ``summary`` only
    when something distinguishes them; nothing in the stream does today, so
    the count is 0. Title and summary side calls do not emit a session step."""
    steps: list[dict] = []
    by_message: dict[str, dict] = {}
    current: dict | None = None
    synthetic = 0
    warnings: list[str] = []
    post_compaction = False
    for event in events:
        kind, part = event["type"], _part(event)
        if kind == "step_start":
            current = {"started_ms": event.get("timestamp"), "session_id": event.get("sessionID"),
                       "message_id": part.get("messageID"), "tools": [], "texts": [], "reasoning": [],
                       "finish": None, "finished_ms": None, "kind": "main"}
            steps.append(current)
            if current["message_id"]:
                by_message[current["message_id"]] = current
            post_compaction = False
            continue
        if kind not in ("tool_use", "text", "reasoning", "step_finish"):
            continue  # error events are run-level; the runner reads them from the stream
        message_id = part.get("messageID")
        if kind == "text" and _synthetic_continue(part) and message_id not in by_message:
            # The continue prompt arrives with no open step, after the compaction
            # summary has finished. It is not model output and does not open one.
            synthetic += 1
            warnings.append(IMPLICIT_TEXT_WARNING)
            if current is None and steps and steps[-1]["kind"] == "main":
                steps[-1]["kind"] = "compaction"
                post_compaction = True
            continue
        step = by_message.get(message_id) or current
        if step is None:
            if kind == "text" and post_compaction:
                warnings.append(IMPLICIT_TEXT_WARNING)
                continue
            raise TraceError("events_malformed", f"{kind} event before any step_start")
        if kind == "tool_use":
            step["tools"].append(part)
        elif kind == "text":
            step["texts"].append(part)
        elif kind == "reasoning":
            step["reasoning"].append(part)
        else:
            step["finish"], step["finished_ms"] = part, event.get("timestamp")
            if step is current:
                current = None
    return OpenCodeParse(steps, synthetic, warnings)


def opencode_steps(events: list[dict]) -> list[dict]:
    """Main-agent steps only. Compaction summary steps are left out so they
    are not paired with answered main wire calls. A synthetic continue text
    does not open a step and does not raise."""
    return parse_opencode(events).by_kind("main")


def _call_index(record: dict):
    index = record.get("call_index")
    return (not isinstance(index, int), index or 0)


def _answered_main(record: dict) -> bool:
    return record.get("call_role", "main") != "side" and record.get("status", 200) == 200


def _answered_side(record: dict, side_kind: str) -> bool:
    return (record.get("call_role") == "side" and record.get("side_kind") == side_kind
            and record.get("status", 200) == 200)


def _thinking_of(record: dict) -> tuple[int | None, str]:
    """``(thinking tokens, status)`` for a wire record or a wire summary row.

    A full wire record uses ``usage_from_response``. A summary row
    (``thinking_tokens`` at the top level, no wire schema) treats null as
    unreported and an int, including 0, as reported."""
    if record.get("schema") == WIRE_SCHEMA and record.get("provider_wire") in WIRES:
        usage = usage_from_response(record["provider_wire"], record.get("response_usage"), 1)
        return usage["thinking_tokens"], usage["thinking_tokens_status"]
    if "thinking_tokens" in record:
        value = record["thinking_tokens"]
        if isinstance(value, bool) or not isinstance(value, int):
            return None, "unreported"
        return value, "reported"
    return None, "unreported"


def _event_reasoning(step: dict) -> int:
    """OpenCode's own ``step_finish.tokens.reasoning``. Not the source of truth."""
    tokens = (step.get("finish") or {}).get("tokens") or {}
    reasoning = tokens.get("reasoning") if isinstance(tokens, dict) else None
    if isinstance(reasoning, bool) or not isinstance(reasoning, int):
        return 0
    return reasoning


def trace_side_counts(events: list[dict] | OpenCodeParse, wire_records: list[dict]) -> dict:
    """Trial-row counts from the event stream joined to wire calls.

    ``steps`` is answered main calls paired with main steps.
    ``thinking_tokens`` sums reported main-step usage (null is omitted, and
    the total is null when nothing was reported). ``compaction_thinking_tokens``
    sums the provider usage of the compaction calls paired, in ``call_index``
    order, with compaction steps; null usage counts as 0, and the total is 0
    when nothing was compacted. It is never added to ``thinking_tokens``.
    OpenCode's own reasoning counter on those steps is returned as
    ``compaction_event_reasoning_tokens`` and is not that total: when the two
    differ, the provider usage stands. A length mismatch is a warning, and
    only the paired prefix is summed."""
    parsed = events if isinstance(events, OpenCodeParse) else parse_opencode(events)
    warnings = list(parsed.trace_warnings)
    main_steps = parsed.by_kind("main")
    compaction_steps = parsed.by_kind("compaction")
    summary_steps = parsed.by_kind("summary")
    main = sorted((w for w in wire_records if _answered_main(w)), key=_call_index)
    compaction = sorted((w for w in wire_records if _answered_side(w, "compaction")), key=_call_index)
    if len(main_steps) != len(main):
        warnings.append(f"step_call_mismatch: {len(main_steps)} main OpenCode steps "
                        f"but {len(main)} main wire calls")
    if len(compaction_steps) != len(compaction):
        warnings.append(f"compaction_step_call_mismatch: {len(compaction_steps)} compaction steps "
                        f"but {len(compaction)} compaction wire calls")
    main_obs = [_thinking_of(wire) for _step, wire in zip(main_steps, main)]
    reported = [tokens for tokens, _status in main_obs if isinstance(tokens, int)]
    statuses = [status for _tokens, status in main_obs]
    comp_tokens = []
    for _step, wire in zip(compaction_steps, compaction):
        tokens, _status = _thinking_of(wire)
        comp_tokens.append(tokens if isinstance(tokens, int) else 0)
    return {
        "steps": len(main_steps),
        "compaction_steps": len(compaction_steps),
        "summary_steps": len(summary_steps),
        "synthetic_continue_messages": parsed.synthetic_continue_messages,
        "thinking_tokens": sum(reported) if reported else None,
        "thinking_tokens_status": {key: statuses.count(key) for key in sorted(set(statuses))},
        "compaction_thinking_tokens": sum(comp_tokens),
        "compaction_event_reasoning_tokens": sum(_event_reasoning(step) for step in compaction_steps),
        "trace_warnings": warnings,
    }


# ---------------------------------------------------------------- wire records


def _get(obj: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def thinking_setting(wire: str, body: dict) -> dict:
    """The explicit thinking setting on a request body, per wire:
    Anthropic ``thinking`` (plus ``output_config.effort``), OpenAI chat
    ``reasoning_effort`` / ``reasoning``, Gemini
    ``generationConfig.thinkingConfig``. ``explicit`` is False when absent."""
    if wire == "anthropic":
        value = body.get("thinking")
        effort = _get(body, "output_config", "effort")
        explicit = isinstance(value, dict) and isinstance(value.get("type"), str)
        out = {"explicit": explicit, "field": "thinking", "value": value}
        if effort is not None:
            out["effort"] = effort
        return out
    if wire == "openai_chat":
        for field in ("reasoning_effort", "reasoning"):
            value = body.get(field)
            if isinstance(value, str) or (isinstance(value, dict) and value):
                return {"explicit": True, "field": field, "value": value}
        return {"explicit": False, "field": "reasoning_effort", "value": None}
    config = _get(body, "generationConfig", "thinkingConfig")
    field = "generationConfig.thinkingConfig"
    if config is None:
        config, field = _get(body, "generation_config", "thinking_config"), "generation_config.thinking_config"
    return {"explicit": isinstance(config, dict) and bool(config), "field": field, "value": config}


# Response usage counters per wire: (input, output, thinking paths, cache read, cache write).
_USAGE_FIELDS = {
    "anthropic": {
        "input": ("input_tokens",), "output": ("output_tokens",),
        "thinking": (("output_tokens_details", "thinking_tokens"), ("thinking_tokens",)),
        "cache_read": ("cache_read_input_tokens",), "cache_write": ("cache_creation_input_tokens",),
    },
    "openai_chat": {
        "input": ("prompt_tokens",), "output": ("completion_tokens",),
        "thinking": (("completion_tokens_details", "reasoning_tokens"),),
        "cache_read": ("prompt_tokens_details", "cached_tokens"), "cache_write": None,
    },
    "gemini": {
        "input": ("promptTokenCount",), "output": ("candidatesTokenCount",),
        "thinking": (("thoughtsTokenCount",),),
        "cache_read": ("cachedContentTokenCount",), "cache_write": None,
    },
}


def _count(usage: dict, path, *, required: bool, step: int, label: str) -> int | None:
    value = _get(usage, *path)
    if value is None:
        if required:
            raise TraceError("usage_malformed", f"usage has no {'.'.join(path)} ({label})", step)
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TraceError("usage_malformed", f"usage {'.'.join(path)} is {value!r}, not a count", step)
    return value


def usage_from_response(wire: str, usage: Any, step: int) -> dict:
    """Normalize the provider's response usage. Input and output counts are
    required; thinking and cache counts are recorded when reported. Gemini
    omits ``candidatesTokenCount`` when nothing visible was generated, so its
    output count defaults to 0."""
    if usage is None:
        raise TraceError("usage_missing", "the response carried no usage object", step)
    if not isinstance(usage, dict):
        raise TraceError("usage_malformed", f"usage is {type(usage).__name__}, not an object", step)
    fields = _USAGE_FIELDS[wire]
    out_required = wire != "gemini"
    thinking, thinking_field = None, None
    for path in fields["thinking"]:
        value = _count(usage, path, required=False, step=step, label="thinking")
        if value is not None:
            thinking, thinking_field = value, ".".join(path)
            break
    output = _count(usage, fields["output"], required=out_required, step=step, label="output")
    return {
        "source": "response.usage",
        "input_tokens": _count(usage, fields["input"], required=True, step=step, label="input"),
        "output_tokens": output if output is not None else 0,
        "thinking_tokens": thinking,
        "thinking_tokens_field": thinking_field,
        "cache_read_tokens": (_count(usage, fields["cache_read"], required=False, step=step, label="cache read")
                              if fields["cache_read"] else None),
        "cache_write_tokens": (_count(usage, fields["cache_write"], required=False, step=step, label="cache write")
                               if fields["cache_write"] else None),
        # Explicit, so an unreported count is never read as "0 thinking". anthropic and openai_chat output counts
        # include thinking (max_tokens caps both); Gemini's candidatesTokenCount excludes thoughtsTokenCount.
        "thinking_tokens_status": "reported" if thinking is not None else "unreported",
        "output_tokens_include_thinking": wire in ("anthropic", "openai_chat"),
        "raw": usage,
    }


def _block_text(content: Any) -> Any:
    if isinstance(content, list):
        texts = [b.get("text") for b in content if isinstance(b, dict) and isinstance(b.get("text"), str)]
        return "\n".join(texts) if texts else content
    return content


def _match_gemini_responses(calls: list[dict], responses: list[dict]) -> list[Any]:
    """The ``functionResponse.response`` for each ``functionCall``: by ``id``
    when the call carries one and a response has the same id, otherwise the
    next unused response with the same name, in order. So repeated or parallel
    calls to one tool each get their own result."""
    used: set[int] = set()
    out = []
    for call in calls:
        pick = None
        if call.get("id") is not None:
            pick = next((i for i, r in enumerate(responses) if i not in used and r.get("id") == call["id"]), None)
        if pick is None:
            pick = next((i for i, r in enumerate(responses) if i not in used and r.get("id") in (None, call.get("id"))
                         and r.get("name") == call.get("name")), None)
        if pick is None:
            out.append(None)
            continue
        used.add(pick)
        out.append(responses[pick].get("response"))
    return out


def tool_calls_from_next_request(wire: str, body: dict | None) -> list[dict]:
    """Tool calls of the previous assistant turn, as the next request replays
    them with their results. At the pin OpenCode's JSON stream emits only
    *completed* tools, so errored calls are recovered from here."""
    if not isinstance(body, dict):
        return []
    if wire == "gemini":
        contents = body.get("contents") or []
        model_at = max((i for i, c in enumerate(contents) if isinstance(c, dict) and c.get("role") == "model"),
                       default=None)
        if model_at is None:
            return []
        responses = [p["functionResponse"] for c in contents[model_at + 1:] if isinstance(c, dict)
                     for p in c.get("parts") or [] if isinstance(p, dict) and isinstance(p.get("functionResponse"), dict)]
        calls_raw = [p["functionCall"] for p in contents[model_at].get("parts") or []
                     if isinstance(p, dict) and isinstance(p.get("functionCall"), dict)]
        return [{"call_id": fc.get("id"), "name": fc.get("name"), "arguments": fc.get("args"),
                 "result": result, "is_error": None}
                for fc, result in zip(calls_raw, _match_gemini_responses(calls_raw, responses))]
    messages = body.get("messages") or []
    asst_at = max((i for i, m in enumerate(messages) if isinstance(m, dict) and m.get("role") == "assistant"),
                  default=None)
    if asst_at is None:
        return []
    assistant, after = messages[asst_at], messages[asst_at + 1:]
    if wire == "openai_chat":
        results = {m.get("tool_call_id"): m.get("content") for m in after
                   if isinstance(m, dict) and m.get("role") == "tool"}
        calls = []
        for call in assistant.get("tool_calls") or []:
            fn = call.get("function") or {}
            args = fn.get("arguments")
            try:
                args = json.loads(args) if isinstance(args, str) else args
            except json.JSONDecodeError:
                pass
            calls.append({"call_id": call.get("id"), "name": fn.get("name"), "arguments": args,
                          "result": _block_text(results.get(call.get("id"))), "is_error": None})
        return calls
    results = {}
    for m in after:
        for b in m.get("content") or [] if isinstance(m, dict) and isinstance(m.get("content"), list) else []:
            if isinstance(b, dict) and b.get("type") == "tool_result":
                results[b.get("tool_use_id")] = b
    calls = []
    content = assistant.get("content")
    for b in content if isinstance(content, list) else []:
        if isinstance(b, dict) and b.get("type") == "tool_use":
            result = results.get(b.get("id")) or {}
            calls.append({"call_id": b.get("id"), "name": b.get("name"), "arguments": b.get("input"),
                          "result": _block_text(result.get("content")), "is_error": result.get("is_error")})
    return calls


# ---------------------------------------------------------------- one step


def _tool_calls(step: dict, recovered: list[dict]) -> list[dict]:
    calls = []
    for part in step["tools"]:
        state = part.get("state") or {}
        calls.append({"call_id": part.get("callID"), "name": part.get("tool"), "arguments": state.get("input"),
                      "result": state.get("output", state.get("error")), "status": state.get("status"),
                      "source": "opencode.tool_use"})
    seen = {c["call_id"] for c in calls}
    for call in recovered:
        if call["call_id"] in seen:
            continue
        calls.append({"call_id": call["call_id"], "name": call["name"], "arguments": call["arguments"],
                      "result": call["result"], "status": "error" if call["is_error"] else "unreported",
                      "source": "next_request"})
    return calls


def _thinking(step: dict, wire: str, setting: dict, thinking_tokens: int | None,
              count_tokens: Callable[[str], tuple[int | None, str]] | None = None) -> dict:
    """What the model returned as thinking, with a kind so analysis can tell
    full thinking from summaries, redactions and nothing at all. ``chars`` is
    the text's length; ``flag`` marks reported-zero-with-text. ``tokens_counted``
    is our own count of the text (``count_tokens``), recorded beside the usage
    value and never in place of it."""
    parts = step["reasoning"]
    text = "\n\n".join(p.get("text", "") for p in parts if isinstance(p.get("text"), str) and p.get("text").strip())
    metadata = [p.get("metadata") for p in parts if p.get("metadata")]
    redacted = any("redacted" in json.dumps(m).lower() for m in metadata)
    if redacted and not text:
        kind, rule = "redacted", "reasoning parts carry only redacted data"
    elif not text:
        kind, rule = (("omitted", "server reported thinking tokens but returned no thinking text")
                      if thinking_tokens else ("none", "no thinking text and no thinking tokens"))
    elif wire == "gemini":
        kind, rule = "summary", "Gemini returns rolling thought summaries, not full thinking"
    elif wire == "anthropic":
        display = (setting.get("value") or {}).get("display") if isinstance(setting.get("value"), dict) else None
        kind, rule = ("full", "anthropic thinking.display=full") if display == "full" else (
            "summary", "Claude 4+ returns summarized thinking unless display=full")
    else:
        kind, rule = "full", "OpenAI-chat reasoning content is the model's own reasoning text"
    flag = (("reported_zero_text_present" if thinking_tokens == 0 else
             "reported_absent_text_present" if thinking_tokens is None else None) if text else None)
    counted, counted_by = (count_tokens(text) if count_tokens and text else (None, None))
    return {"kind": kind, "text": text, "parts": len(parts), "source": "opencode.reasoning", "rule": rule,
            "metadata": metadata, "chars": len(text), "flag": flag,
            "tokens_counted": counted, "tokens_counted_by": counted_by}


def _stripped_count(wire: dict) -> int:
    count = wire.get("stripped_side_thinking_blocks") or 0
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        return 0
    return count


def _iso(ms: Any) -> str | None:
    if isinstance(ms, (int, float)) and not isinstance(ms, bool):
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(timespec="milliseconds")
    return None


def _check_wire(record: Any, index: int) -> dict:
    if not isinstance(record, dict) or record.get("schema") != WIRE_SCHEMA:
        raise TraceError("wire_malformed", f"wire record {index} is not {WIRE_SCHEMA}")
    if record.get("provider_wire") not in WIRES:
        raise TraceError("wire_malformed", f"wire record {index} has provider_wire {record.get('provider_wire')!r}")
    return record


def build_trace(events: list[dict], wire_records: list[dict], *, run: dict | None = None,
                cost_fn: Callable[[dict], tuple[float | None, str]] | None = None,
                require_explicit_thinking: bool = True,
                count_thinking_tokens: Callable[[str], tuple[int | None, str]] | None = None) -> list[dict]:
    """One ``step/v1`` record per main OpenCode step. Compaction summary steps
    are not records here; their thinking is ``trace_side_counts``'
    ``compaction_thinking_tokens``. ``cost_fn(record)`` returns
    ``(usd, source)`` to replace OpenCode's per-step cost (the runner's
    ledger-priced cost hook). ``count_thinking_tokens(text)`` returns
    ``(count, label)`` for ``thinking.tokens_counted`` (our own count, e.g.
    o200k_harmony for gpt-oss); it never touches ``usage.thinking_tokens``."""
    pin = load_pin()
    steps = opencode_steps(events)
    wires = [_check_wire(r, i) for i, r in enumerate(wire_records, 1)]
    # A main call that failed (4xx/5xx) produced no OpenCode step: OpenCode's client retried it. Only answered
    # calls pair with steps; failed ones stay in wire.jsonl (classify_4xx / retried_4xx).
    # Compaction calls are side calls and pair with compaction steps, not these.
    main = sorted((w for w in wires if w.get("call_role", "main") != "side" and w.get("status", 200) == 200),
                  key=lambda w: w.get("call_index", 0))
    if len(main) != len(steps):
        raise TraceError("step_call_mismatch",
                         f"{len(steps)} main OpenCode steps but {len(main)} main wire calls")
    records = []
    for index, (step, wire) in enumerate(zip(steps, main), 1):
        kind, body = wire["provider_wire"], wire.get("request")
        if not isinstance(body, dict):
            raise TraceError("request_missing", "the wire record has no request body", index)
        setting = thinking_setting(kind, body)
        if require_explicit_thinking and not setting["explicit"]:
            raise TraceError("thinking_unset", f"no explicit {setting['field']} on the request", index)
        usage = usage_from_response(kind, wire.get("response_usage"), index)
        following = main[index]["request"] if index < len(main) else None
        finish = step["finish"] or {}
        record = {
            "schema": TRACE_SCHEMA,
            "run": dict(run or {}),
            "harness": {"name": "opencode", "sha": pin["sha"], "package_version": pin["package_version"]},
            "step": index,
            "session_id": step["session_id"],
            "message_id": step["message_id"],
            "started_at": _iso(step["started_ms"]),
            "finished_at": _iso(step["finished_ms"]),
            "model": {"requested": wire.get("requested_model"), "served": wire.get("upstream_model"),
                      "wire": kind},
            "request": {"payload": body, "thinking_setting": setting, "call_index": wire.get("call_index"),
                        "sent_at": wire.get("ts"), "response_arrived": bool(wire.get("response_arrived")),
                        "first_byte_at": wire.get("first_byte_at")},
            "tool_calls": _tool_calls(step, tool_calls_from_next_request(kind, following)),
            "assistant_text": "\n\n".join(p.get("text", "") for p in step["texts"] if p.get("text")),
            "thinking": _thinking(step, kind, setting, usage["thinking_tokens"], count_thinking_tokens),
            "usage": usage,
            "cost": {"usd": finish.get("cost"), "source": "opencode.step_finish" if "cost" in finish else None},
            "finish_reason": finish.get("reason"),
            "opencode_tokens": finish.get("tokens"),
            # 0 when the wire record predates the field or this step replayed no side-signed block.
            "stripped_side_thinking_blocks": _stripped_count(wire),
        }
        if record["thinking"].get("flag") == "reported_zero_text_present":
            usage["thinking_tokens_status"] = "reported_zero_text_present"  # contradicts the text: don't read as 0
        if cost_fn is not None:
            usd, source = cost_fn(record)
            record["cost"] = {"usd": usd, "source": source}
        records.append(record)
    return records


def write_trace(path: Path, records: list[dict]) -> Path:
    """Write the step records as JSONL, atomically (temp file + rename)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    return path


def wire_records_from_proxy_ledger(ledger_rows: list[dict], requests_root: Path | None = None) -> list[dict]:
    """Wire records from the Vertex proxy ledger (Anthropic Messages calls).
    The request body comes from the proxy's raw request capture
    (``cc_identity_stripped.capture.raw_request_file``, relative to
    ``requests_root``) when the proxy ran with capture on; otherwise it is
    None and ``build_trace`` fails with ``request_missing``."""
    records = []
    for index, row in enumerate((r for r in ledger_rows if r.get("record_type", "request") == "request"), 1):
        body = None
        rel = _get(row, "cc_identity_stripped", "capture", "raw_request_file")
        if requests_root is not None and isinstance(rel, str):
            path = Path(requests_root) / rel
            if path.is_file():
                body = json.loads(path.read_text(encoding="utf-8"))
        records.append({
            "schema": WIRE_SCHEMA, "call_index": index, "ts": row.get("ts"),
            "provider_wire": "anthropic", "call_role": row.get("call_role", "main"),
            "requested_model": row.get("requested_model"), "upstream_model": row.get("upstream_model"),
            "request": body, "response_usage": row.get("usage"), "status": row.get("status"),
        })
    return records


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Build a per-step trace from an OpenCode run")
    parser.add_argument("--events", type=Path, required=True, help="OpenCode --format json output or transcript")
    parser.add_argument("--wire", type=Path, required=True, help="wire/v1 JSONL, one record per model call")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--run", type=json.loads, default={}, help="run metadata JSON (task, model, trial, ...)")
    args = parser.parse_args(argv)
    events = parse_events(args.events.read_text(encoding="utf-8").splitlines())
    wire = [json.loads(line) for line in args.wire.read_text(encoding="utf-8").splitlines() if line.strip()]
    try:
        records = build_trace(events, wire, run=args.run)
    except TraceError as exc:
        print(f"trace: {exc}", flush=True)
        return 2
    print(write_trace(args.out, records))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
