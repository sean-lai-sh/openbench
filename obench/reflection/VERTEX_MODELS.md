# Reflection-loop models on Vertex AI (SEA-105)

Every scored reflection-loop run uses exactly these three models on Vertex AI.
The registry is `vertex_models.py` (`MODELS`), and `resolve()` accepts only
these keys. It has no aliases, no default, and no Sonnet, Qwen or non-Vertex
route. Don't pool these results with earlier Sonnet or harness-comparison rows.

| Key | Model | Vertex model ID | Publisher | Location | Wire | Upstream (POST, `aiplatform.googleapis.com`) |
|---|---|---|---|---|---|---|
| `gemini-4-carbon` | Gemini 4 Carbon | `gemini-4-carbon` | `google` | `global` | Gemini `generateContent` | `/v1/projects/P/locations/global/publishers/google/models/gemini-4-carbon:streamGenerateContent?alt=sse` |
| `claude-opus-5-5` | Claude Opus 5.5 | `claude-opus-5-5` | `anthropic` | `global` | Anthropic Messages | `/v1/projects/P/locations/global/publishers/anthropic/models/claude-opus-5-5:streamRawPredict` |
| `gpt-oss-120b` | gpt-oss 120B | `gpt-oss-120b-maas` (body: `openai/gpt-oss-120b-maas`) | `openai` | `global` | OpenAI Chat Completions | `/v1/projects/P/locations/global/endpoints/openapi/chat/completions` |

**Headers:** none beyond `Authorization: Bearer <ADC token>`. The proxy drops
the client's placeholder key. Anthropic on Vertex takes `anthropic_version`
in the body (`vertex-2023-10-16`) and no `model` field. `anthropic-beta`
is passed through.

**Regions:**
- **Carbon:** `global`, plus the `us` and `eu` multi-regions. ML processing is `us`/`eu`.
- **Opus 5.5:** `global`, plus `us` and `eu` through the multi-region hosts. Regional endpoints serve only Sonnet 4.6 and earlier.
- **gpt-oss 120B:** `global`, with processing in `us`.

All three use `global`.

## Thinking (set explicitly on every request by the proxy)

| Model | Setting sent | What comes back |
|---|---|---|
| Gemini 4 Carbon | `generationConfig.thinkingConfig = {"thinkingLevel": "HIGH", "includeThoughts": true}`. Allowed levels are `LOW`, `MEDIUM` (the model's default) and `HIGH`; `thinking_budget` and `MINIMAL` return 400. | **Rolling thought summaries only.** The trace records `thinking.kind = summary` (or `omitted` when tokens are billed but no text returns). That is expected, not a smoke failure. Tokens come from `usageMetadata.thoughtsTokenCount`. |
| Claude Opus 5.5 | `thinking = {"type": "adaptive"}`. The proxy drops `temperature`/`top_p`/`top_k` when present, since they conflict with thinking. | Summarized thinking blocks. Tokens come from `usage.output_tokens_details.thinking_tokens`. |
| gpt-oss 120B | `reasoning_effort = "high"` is the explicit setting. | `reasoning_content` text. **Known Vertex gap:** the model page lists "Thinking: Not supported", and usage reports `completion_tokens_details.reasoning_tokens = 0` even at high effort. Handled like Carbon and Opus. The trace records the usage value as reported: `0` (flag `reported_zero_text_present`), or **absent**, because the 2026-11-13 VM smoke's usage had only prompt/completion/total tokens. Absent is recorded as `null`, with flag `reported_absent_text_present` when reasoning text came back. Vertex reports the served model as `openai/gpt-oss-120b-maas`, which is accepted, with the text and `thinking.chars`. Optionally, `thinking.tokens_counted` is our own `o200k_harmony` count of the text (`pip install 'obench[reflection]'`, i.e. tiktoken>=0.11; labelled computed). It never replaces or pools with the usage value. |

**gpt-oss thinking counts are not comparable with Carbon's and Opus's.**
Their usage reports real thinking-token counts, while gpt-oss's usage
reports 0. Compare gpt-oss thinking by `thinking.chars` or
`thinking.tokens_counted`. Never pool those with any model's usage value, and
note this in every writeup that reports thinking tokens.

The smoke's `usage_thinking` check passes gpt-oss on "reported 0, text
present" (flagged) and fails it only when the reasoning text is missing or
empty. Carbon and Opus pass on any reported usage count.

The client's own thinking setting is overridden and recorded in the wire
record's `thinking_enforced`. `HIGH` for Carbon and `high` for gpt-oss are
choices, configurable in `vertex_models.py`.

## Prices (cost logging)

USD per 1M tokens, Standard tier, global. `cost_usd` and `cost_basis` are on
every wire record, and the smoke's `cost` check totals them.

Where a model has no cached-token rate (gpt-oss: Vertex reports
`prompt_tokens_details.cached_tokens` but no cached price is published),
cached tokens are billed at the uncached input rate. That's an upper bound,
marked `cache_read_at_input_rate` in `cost_basis`.

| Model | Input | Output (incl. thinking) | Cache read | Cache write | Verified |
|---|---:|---:|---:|---:|---|
| Claude Opus 5.5 | 4.00 | 20.00 | 0.20 | 5.00 | yes (`thesis/ab/vertex_list_prices.json`, read 2026-10-29) |
| Gemini 4 Carbon | 4.00 | 20.00 | 0.40 (assumed 10% of input) | n/a | **no.** Reported global SKU. Google announced an introductory $2/$10. |
| gpt-oss 120B | 0.15 | 0.60 | none published: billed at the input rate (estimate) | n/a | **no.** GA announcement rate; current aggregators show $0.09/$0.36. |

Confirm the two unverified rows on the Agent Platform pricing page before any
scored run. The page didn't render for automated reading on 2026-11-13.

## Sources (read 2026-11-13)

- **Gemini 4 Carbon:**
  - https://docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/model-versions (`gemini-4-carbon`, released 2026-11-10)
  - https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/4-carbon (locations; thinking levels)
  - https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/guides/gemini-4-carbon (REST `thinkingConfig.thinkingLevel`; `global` URL)
- **Claude Opus 5.5:**
  - https://platform.claude.com/docs/en/build-with-claude/claude-models-on-google-cloud/google-managed (model ID table, endpoint types, `rawPredict`/`streamRawPredict`, `anthropic_version`)
- **gpt-oss 120B:**
  - https://docs.cloud.google.com/vertex-ai/generative-ai/docs/maas/openai/gpt-oss-120b (`gpt-oss-120b-maas`; `global`; "Thinking: Not supported")
  - https://docs.cloud.google.com/vertex-ai/generative-ai/docs/maas/call-open-model-apis (OpenAI-compatible `.../locations/global/endpoints/openapi/chat/completions`; body `model: "openai/gpt-oss-120b-maas"`; streaming usage in the final chunk)
  - https://discuss.ai.google.dev/t/why-are-reasoning-tokens-for-openai-gpt-oss-120b-maas-always-returned-as-0/109379 (`reasoning_tokens` reported as 0)

## OpenCode wiring

`opencode_config(model, proxy_base)` is passed as `OPENCODE_CONFIG_CONTENT`. It contains:
- a single provider `vertex-<key>`, using `@ai-sdk/google`, `@ai-sdk/anthropic` or `@ai-sdk/openai-compatible`, with `baseURL` set to the proxy route `/m/<key>/...`;
- `enabled_providers: [vertex-<key>]`, so no other provider can load;
- `model` and `small_model` both set to that model, so titles stay on it.

The smoke strips provider API keys and isolates OpenCode's home.

## Shared code

The proxy and registry are new and reflection-only. They reuse two pieces
unchanged:
- `thesis.ab.vertex_anthropic_proxy.AdcToken`, the ADC token source;
- the Opus price from `thesis/ab/vertex_list_prices.json`, copied into the registry.

No harness-comparison runner, adapter or proxy is modified.
