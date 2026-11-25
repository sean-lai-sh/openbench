# Reflection-loop per-step trace (`openbench.reflection.step/v1`)

Writer: `obench/reflection/trace.py` (`build_trace`, `write_trace`; CLI
`python3 -m obench.reflection.trace --events … --wire … --out …`).
Tests: `obench/tests/test_reflection_trace.py`.

One trace file per OpenCode run: JSONL, one object per model step, in step
order, written atomically. A run that fails validation writes nothing and
raises `TraceError` (see [Failures](#failures)).

## Sources

| Source | What it gives | Format |
|---|---|---|
| OpenCode at the pin (`opencode_pin.json`), run with `--format json --thinking` | step boundaries and timestamps, tool calls, assistant text, thinking text, OpenCode's own cost | `step_start`, `tool_use`, `text`, `reasoning`, `step_finish` events |
| Wire records (`openbench.reflection.wire/v1`), one per model call, written where the call is routed | the request body exactly as sent (including the thinking setting), the model actually served, the provider's response `usage` | JSONL, below |

OpenCode step *i* is main wire call *i*. Side calls (`call_role: "side"`,
e.g. title generation) are not steps.

Two things at the pin shape this:
- `reasoning` events are emitted only with `--thinking`.
- `tool_use` is emitted only for *completed* tools.

So errored tool calls are recovered from the next request, which replays the
call together with its result (`tool_calls[].source = "next_request"`).

## Step record

| Field | Type | Req. | Meaning |
|---|---|---|---|
| `schema` | string | yes | `"openbench.reflection.step/v1"` |
| `run` | object | yes | Caller's run metadata (task, model, trial, …); may be `{}` |
| `harness` | object | yes | `{name: "opencode", sha, package_version}` from the pin |
| `step` | int | yes | 1-based step index |
| `session_id` | string\|null | yes | OpenCode session id |
| `message_id` | string\|null | yes | OpenCode assistant message id for the step |
| `started_at` | string\|null | yes | ISO-8601 UTC, from `step_start.timestamp` |
| `finished_at` | string\|null | yes | ISO-8601 UTC, from `step_finish.timestamp`; null if the run died mid-step |
| `model.requested` | string\|null | yes | Model id the harness asked for |
| `model.served` | string\|null | yes | Model the provider actually served (`upstream_model`) |
| `model.wire` | string | yes | `anthropic` \| `openai_chat` \| `gemini` |
| `request.payload` | object | yes | Request body as sent, enough to reproduce the call |
| `request.thinking_setting` | object | yes | `{explicit: bool, field, value[, effort]}`: Anthropic `thinking` (+ `output_config.effort`), OpenAI `reasoning_effort`/`reasoning`, Gemini `generationConfig.thinkingConfig` |
| `request.call_index` | int\|null | yes | The wire record's call index |
| `request.sent_at` | string\|null | yes | The wire record's timestamp (when the request was sent) |
| `request.response_arrived` | bool | yes | Whether an upstream HTTP response was received for this call (headers, including 4xx/5xx). False when the request was sent and nothing came back |
| `request.first_byte_at` | string\|null | yes | ISO-8601 UTC when the first upstream body byte arrived; null if none |
| `tool_calls[]` | array | yes | `{call_id, name, arguments, result, status, source}`; `source` is `opencode.tool_use` or `next_request` (errored calls recovered from the next request) |
| `assistant_text` | string | yes | Visible text of the step (`""` if none) |
| `thinking.kind` | string | yes | `full` \| `summary` \| `redacted` \| `omitted` \| `none` |
| `thinking.text` | string | yes | What the model returned as thinking (`""` if nothing) |
| `thinking.parts` | int | yes | Number of reasoning parts |
| `thinking.source` | string | yes | `opencode.reasoning` |
| `thinking.rule` | string | yes | Why `kind` was assigned |
| `thinking.metadata` | array | yes | Reasoning-part metadata (signatures, redacted data) |
| `thinking.chars` | int | yes | Length of `thinking.text` in characters |
| `thinking.flag` | string\|null | yes | `reported_zero_text_present` when usage reports 0 thinking tokens but thinking text came back; `reported_absent_text_present` when usage has no thinking-token field at all but thinking text came back (gpt-oss on Vertex); else null |
| `thinking.tokens_counted` | int\|null | yes | **Our own** token count of `thinking.text` (gpt-oss: `o200k_harmony` via tiktoken). Never replaces, and never pools with, `usage.thinking_tokens`. Null when not computed. |
| `thinking.tokens_counted_by` | string\|null | yes | What computed `tokens_counted` (e.g. `computed: tiktoken o200k_harmony`), or why it wasn't (`unavailable: ...`) |
| `usage.source` | string | yes | `response.usage`: always the provider response |
| `usage.input_tokens` | int | yes | Anthropic `input_tokens`, OpenAI `prompt_tokens`, Gemini `promptTokenCount` |
| `usage.output_tokens` | int | yes | As reported (Anthropic and OpenAI include thinking; Gemini `candidatesTokenCount` doesn't, and defaults to 0 when absent) |
| `usage.thinking_tokens` | int\|null | yes | Anthropic `output_tokens_details.thinking_tokens`, OpenAI `completion_tokens_details.reasoning_tokens`, Gemini `thoughtsTokenCount`; null when not reported |
| `usage.thinking_tokens_field` | string\|null | yes | Which usage field it came from |
| `usage.thinking_tokens_status` | string | yes | `reported`; `unreported` (usage carried no thinking count: `thinking_tokens` is null, **not 0**); or `reported_zero_text_present` (usage says 0 but thinking text came back, so don't read it as 0). Anthropic streams take the count only from the final `message_delta`. The `message_start` snapshot's count is not a measurement. |
| `usage.output_tokens_include_thinking` | bool | yes | True for anthropic and openai_chat, whose output count includes thinking (an upper bound when the count is unreported). False for Gemini, which reports `thoughtsTokenCount` separately. |
| `usage.cache_read_tokens` | int\|null | yes | Anthropic `cache_read_input_tokens`, OpenAI `prompt_tokens_details.cached_tokens`, Gemini `cachedContentTokenCount` |
| `usage.cache_write_tokens` | int\|null | yes | Anthropic `cache_creation_input_tokens`; null where the provider has none |
| `usage.raw` | object | yes | The response usage object, unchanged |
| `cost.usd` | number\|null | yes | OpenCode's step cost, or the runner's (`build_trace(cost_fn=...)`) |
| `cost.source` | string\|null | yes | `opencode.step_finish`, the `cost_fn` source, or null |
| `finish_reason` | string\|null | yes | `step_finish.reason` (`tool-calls`, `stop`, …) |
| `opencode_tokens` | object\|null | yes | OpenCode's own token split. **For comparison only, never the source of truth.** Its `reasoning` is 0 even when the server billed thinking. |

**Thinking tokens are not comparable across models.** `usage.thinking_tokens`
is always what the provider reported. gpt-oss on Vertex reports 0 even when it
returns reasoning text (flagged `reported_zero_text_present`), while Carbon
and Opus report real counts. Compare gpt-oss thinking by `thinking.chars` or
`thinking.tokens_counted`, never by pooling either with the usage value.

**Thinking kinds.**
- `full`: the model's own reasoning text (OpenAI-chat reasoning content, or Anthropic with `display: "full"`).
- `summary`: summaries. Gemini (Carbon) returns rolling thought summaries; Claude 4+ returns summarized thinking by default.
- `redacted`: only redacted data came back.
- `omitted`: the server reported thinking tokens but returned no text.
- `none`: no thinking text and no thinking tokens.

## Wire record (`openbench.reflection.wire/v1`)

| Field | Type | Req. | Meaning |
|---|---|---|---|
| `schema` | string | yes | `"openbench.reflection.wire/v1"` |
| `call_index` | int | yes | 1-based order of the call in the run |
| `ts` | string\|null | no | When the request was sent |
| `provider_wire` | string | yes | `anthropic` \| `openai_chat` \| `gemini` |
| `call_role` | string | no | `main` (default) or `side` |
| `requested_model` | string\|null | no | Model id on the incoming request |
| `upstream_model` | string\|null | yes | Model actually served |
| `request` | object | yes | Request body as sent |
| `response_usage` | object\|null | yes | The provider response's `usage` (`usageMetadata` for Gemini) |
| `status` | int\|null | no | HTTP status |
| `route` | string | no | The proxy route (reflection model key) the call went through (`wire_proxy.py`) |
| `thinking_enforced` | object | no | `{setting, client[, removed]}`: the thinking setting the proxy sent, what the client asked for, and any params dropped as incompatible |
| `cost_usd` | number\|null | no | Per-call cost from `vertex_models.cost_detail` (null only when the response had no usage) |
| `cost_basis` | array\|null | no | What the cost rests on: `list` or `list_unverified`, plus `cache_read_at_input_rate` / `cache_write_at_input_rate` when a model has no cached-token rate and cached tokens were billed at the uncached input rate (an upper-bound estimate) |
| `response_summary` | object\|null | no | Diagnostic counts of what the model returned: `finish_reasons`, `tool_calls`, `text_chars`, `reasoning_chars`. OpenAI-chat (gpt-oss) adds `harmony_markers_in_text` (tool calls left as raw harmony text instead of `tool_calls`) and `text_head` (the first 160 characters of visible text). Anthropic adds `stop_details` when the response carried them (e.g. with `stop_reason: "refusal"`); Gemini adds `safety_ratings` for a candidate with `finishReason: SAFETY` (both read by `wire_proxy.model_refused`). |
| `client_disconnected` | bool | no | The client hung up mid-response. The proxy kept reading upstream, so usage and the summary are complete. |
| `response_bytes` | int | no | Bytes received from upstream |
| `route_repair` | object\|null | no | gpt-oss only: `{applied, tool, method (harmony_recipient\|schema_match), source (reasoning\|content), original_finish_reason}` when the proxy rebuilt a tool call the Vertex route left as text (`gptoss_repair.py`). `response_summary` then describes what OpenCode received, and `upstream_response_summary` what Vertex sent. |
| `upstream_response_summary` | object\|null | no | gpt-oss only: the summary of the response exactly as Vertex sent it, before any repair (on every 200 call) |
| `provider_blocked` | object\|null | no | Gemini: the provider blocked the **prompt** (HTTP 200, `promptFeedback.blockReason`, no candidates): `{blockReason, blockReasonMessage, safetyRatings}`. The proxy tells the executor, which stops the agent; the trial is `provider_blocked` (`wire_proxy.provider_blocked`). |
| `short_circuited` | bool | no | True on a call the proxy refused without sending because the prompt was already blocked (`status: null`, `error: "provider_blocked: not sent"`, HTTP 400 `PROVIDER_BLOCKED` to the client) |
| `stream_error` | string\|null | no | The upstream body failed mid-response (e.g. `ConnectionResetError`, `IncompleteRead`). The record keeps the bytes received; an Anthropic client is sent an SSE `error` event, so the SDK raises instead of ending the turn quietly. |
| `ended_at` | string | no | ISO-8601 UTC time the call finished (response fully read, or failed); `ts` is when it started |
| `response_arrived` | bool | no | True once an upstream HTTP response was received (headers, including 4xx/5xx). False when the request was sent and no response came back (a hang before the agent cap). Every trial's last call is also summarized as `last_vertex_request` on the trial row and in `last_vertex_request.json` beside this file, written when the request is sent and updated when a response or the first body byte arrives, so a hang that never finishes a wire line is still visible |
| `first_byte_at` | string\|null | no | ISO-8601 UTC when the first upstream body byte arrived; null if none |
| `usage_events` | array\|null | no | Anthropic streams: every usage object the response carried, in order (`{event: message_start\|message_delta, usage}`). Shows whether Vertex ever reports a thinking count, and in which event. |
| `upstream_raw` | string\|null | no | gpt-oss only: path, relative to the wire file's directory, of the raw upstream bytes (`upstream-raw/<call_index>.sse\|json`), for every call including errors. Model output only, but scrub it before committing like any transcript. |
| `error` | string | no | Transport error when the upstream was unreachable |
| `usage_error` | string | no | `TraceError` code when the response usage could not be normalized |
| `patch_id` | string | no | The ideation alternative whose patch the proxy applied (SEA-110). The per-op log is in `thinking_enforced.patch_log`. |

The reflection loop's own routes write these directly: `wire_proxy.py`
(SEA-105, one fixed Vertex route per model). `wire_records_from_proxy_ledger`
builds them from the existing harness-comparison Vertex proxy ledger, taking
the request bodies from its raw request capture.

## Failures

`TraceError.code`, with `step` set when the failure is per step:

| Code | When |
|---|---|
| `events_malformed` | A JSON line isn't an OpenCode event, or a part arrives before any `step_start` |
| `wire_malformed` | A wire record isn't `wire/v1`, or has an unknown `provider_wire` |
| `step_call_mismatch` | The number of OpenCode steps differs from the number of answered (status 200) main wire calls. Failed calls that OpenCode retried have no step and are not paired. |
| `request_missing` | A step's wire record has no request body |
| `thinking_unset` | The request has no explicit thinking setting (standing rule: set thinking on every request). `require_explicit_thinking=False` turns this off, for inspection only. |
| `usage_missing` | The response had no usage object |
| `usage_malformed` | Usage isn't an object, a required counter is missing, or a counter isn't a non-negative int |

The CLI prints the error and exits 2.

## Example (one step, Anthropic on Vertex)

```json
{
  "schema": "openbench.reflection.step/v1",
  "run": {"task": "polyglot-rust-c", "model": "claude-opus-5-5", "trial": 1},
  "harness": {"name": "opencode", "sha": "ba54cee55e18b47fb70badc84ae2cbac7c83d258", "package_version": "1.1.61"},
  "step": 2,
  "session_id": "ses_example",
  "message_id": "msg_example2",
  "started_at": "2026-11-12T20:00:01.000+00:00",
  "finished_at": "2026-11-12T20:00:04.500+00:00",
  "model": {"requested": "claude-opus-5-5", "served": "claude-opus-5-5", "wire": "anthropic"},
  "request": {
    "payload": {"model": "claude-opus-5-5", "max_tokens": 32000, "thinking": {"type": "adaptive", "display": "summarized"}, "messages": ["..."]},
    "thinking_setting": {"explicit": true, "field": "thinking", "value": {"type": "adaptive", "display": "summarized"}},
    "call_index": 2,
    "sent_at": "2026-11-12T20:00:01.000Z",
    "response_arrived": true,
    "first_byte_at": "2026-11-12T20:00:01.400Z"
  },
  "tool_calls": [
    {"call_id": "toolu_2", "name": "bash", "arguments": {"command": "cargo build"}, "result": "error[E0425]: …", "status": "error", "source": "next_request"}
  ],
  "assistant_text": "",
  "thinking": {"kind": "summary", "text": "The build failed on an unresolved name…", "parts": 1, "source": "opencode.reasoning", "rule": "Claude 4+ returns summarized thinking unless display=full", "metadata": [], "chars": 40, "flag": null, "tokens_counted": null, "tokens_counted_by": null},
  "usage": {"source": "response.usage", "input_tokens": 12, "output_tokens": 410, "thinking_tokens": 233, "thinking_tokens_field": "output_tokens_details.thinking_tokens", "thinking_tokens_status": "reported", "output_tokens_include_thinking": true, "cache_read_tokens": 15840, "cache_write_tokens": 512, "raw": {"input_tokens": 12, "output_tokens": 410, "cache_read_input_tokens": 15840, "cache_creation_input_tokens": 512, "output_tokens_details": {"thinking_tokens": 233}}},
  "cost": {"usd": 0.0412, "source": "opencode.step_finish"},
  "finish_reason": "tool-calls",
  "opencode_tokens": {"input": 12, "output": 177, "reasoning": 233, "cache": {"read": 15840, "write": 512}}
}
```
