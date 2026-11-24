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
| `request.sent_at` | string\|null | yes | The wire record's timestamp |
| `tool_calls[]` | array | yes | `{call_id, name, arguments, result, status, source}`; `source` is `opencode.tool_use` or `next_request` (errored calls recovered from the next request) |
| `assistant_text` | string | yes | Visible text of the step (`""` if none) |
| `thinking.kind` | string | yes | `full` \| `summary` \| `redacted` \| `omitted` \| `none` |
| `thinking.text` | string | yes | What the model returned as thinking (`""` if nothing) |
| `thinking.parts` | int | yes | Number of reasoning parts |
| `thinking.source` | string | yes | `opencode.reasoning` |
| `thinking.rule` | string | yes | Why `kind` was assigned |
| `thinking.metadata` | array | yes | Reasoning-part metadata (signatures, redacted data) |
| `usage.source` | string | yes | `response.usage`: always the provider response |
| `usage.input_tokens` | int | yes | Anthropic `input_tokens`, OpenAI `prompt_tokens`, Gemini `promptTokenCount` |
| `usage.output_tokens` | int | yes | As reported (Anthropic and OpenAI include thinking; Gemini `candidatesTokenCount` doesn't, and defaults to 0 when absent) |
| `usage.thinking_tokens` | int\|null | yes | Anthropic `output_tokens_details.thinking_tokens`, OpenAI `completion_tokens_details.reasoning_tokens`, Gemini `thoughtsTokenCount`; null when not reported |
| `usage.thinking_tokens_field` | string\|null | yes | Which usage field it came from |
| `usage.cache_read_tokens` | int\|null | yes | Anthropic `cache_read_input_tokens`, OpenAI `prompt_tokens_details.cached_tokens`, Gemini `cachedContentTokenCount` |
| `usage.cache_write_tokens` | int\|null | yes | Anthropic `cache_creation_input_tokens`; null where the provider has none |
| `usage.raw` | object | yes | The response usage object, unchanged |
| `cost.usd` | number\|null | yes | OpenCode's step cost, or the runner's (`build_trace(cost_fn=...)`) |
| `cost.source` | string\|null | yes | `opencode.step_finish`, the `cost_fn` source, or null |
| `finish_reason` | string\|null | yes | `step_finish.reason` (`tool-calls`, `stop`, …) |
| `opencode_tokens` | object\|null | yes | OpenCode's own token split. **For comparison only, never the source of truth.** Its `reasoning` is 0 even when the server billed thinking. |

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

`wire_records_from_proxy_ledger` builds these from the existing Vertex proxy
ledger, taking the request bodies from its raw request capture.

## Failures

`TraceError.code`, with `step` set when the failure is per step:

| Code | When |
|---|---|
| `events_malformed` | A JSON line isn't an OpenCode event, or a part arrives before any `step_start` |
| `wire_malformed` | A wire record isn't `wire/v1`, or has an unknown `provider_wire` |
| `step_call_mismatch` | The number of OpenCode steps differs from the number of main wire calls |
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
    "sent_at": "2026-11-12T20:00:01.000Z"
  },
  "tool_calls": [
    {"call_id": "toolu_2", "name": "bash", "arguments": {"command": "cargo build"}, "result": "error[E0425]: …", "status": "error", "source": "next_request"}
  ],
  "assistant_text": "",
  "thinking": {"kind": "summary", "text": "The build failed on an unresolved name…", "parts": 1, "source": "opencode.reasoning", "rule": "Claude 4+ returns summarized thinking unless display=full", "metadata": []},
  "usage": {"source": "response.usage", "input_tokens": 12, "output_tokens": 410, "thinking_tokens": 233, "thinking_tokens_field": "output_tokens_details.thinking_tokens", "cache_read_tokens": 15840, "cache_write_tokens": 512, "raw": {"input_tokens": 12, "output_tokens": 410, "cache_read_input_tokens": 15840, "cache_creation_input_tokens": 512, "output_tokens_details": {"thinking_tokens": 233}}},
  "cost": {"usd": 0.0412, "source": "opencode.step_finish"},
  "finish_reason": "tool-calls",
  "opencode_tokens": {"input": 12, "output": 177, "reasoning": 233, "cache": {"read": 15840, "write": 512}}
}
```
