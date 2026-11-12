# PR #245 matched-config re-smoke at 29236b59 (2026-11-12)

This is a smoke, not a result. Nothing here is scored or poolable.
- The Pi arm ran on both models. Every request was traced, and each model sent one fixed thinking setting on every request.
- The OpenCode arm failed on both models before sending any request. The cause is **not** `provider_pin_mismatch`; see below.

## Setup
- **Head:** `29236b59cb59ed4190fe9443c9f588023f9d2586` (#245), from a fresh worktree.
- **Environment:** thesis-h1-cpu-2, image `h1-env:1027-strace`, Vertex global, bridge network, `--require-model-match`.
- **Task:** regex-chess. Every cell passed `--matched-config`, and the Opus cells also passed `--matched-effort low`.
- **Order:** one model at a time, Pi then OpenCode, Sonnet 5.5 then Opus 5.5. The total cap was $6.
- **Launch:** `raw/m245b-launch.sh` runs `raw/m245b-batch.py`. Pi's `TASK` is set on the loaded module, the same way as the #196 `pvo-batch.py`. No repo code was edited.
- **Analysis:** `raw/analysis.json` (from `raw/m245b-an.py`) is computed from the proxy ledgers. The thinking counts come from server `usage.output_tokens_details.thinking_tokens`, not from `tokens_reasoning`.

## Opus 5.5 effort probe (`raw/opus-effort-probe/`)
- **Method:** one minimal request ("Reply with the single word OK.", max_tokens 32) per value, sent through the #245 proxy with `OBENCH_MATCHED_CONFIG=1` and `{"type":"adaptive"}`. Values were tried lowest first, stopping at the first 200.
- **`minimal`: 400.** Verbatim body: `{"type":"error","error":{"type":"invalid_request_error","message":"output_config.effort: Input should be 'low', 'medium', 'high', 'xhigh' or 'max'"},"request_id":"req_vrtx_011CgyiqvyMqZknkdCperxEb"}`
- **`low`: 200.** 0 thinking tokens. This is the value chosen.
- **`medium`:** not sent, because `low` already returned 200.

So the lowest accepted Opus 5.5 effort is `low`. The 400 lists the allowed set: low, medium, high, xhigh, max.

## Per cell

| cell | requests / traced | status | upstream | thinking_json | output_config_json | thinking_tokens (sum, nonzero calls) | outcome | spend | wall |
|---|---|---|---|---|---|---|---|---|---|
| Pi Sonnet `9f0fac09184d3575` | 34 / 34 | all 200 | claude-sonnet-5-5 | `{"type":"between_tools"}` on all 34 | absent | 7,528 (29 of 34) | solved (checker 0) | $0.533 | 554 s |
| OpenCode Sonnet `a097f60a76d15e59` | 0 | none | none | none | none | none | infra: OpenCode error, then wrong_answer (`missing re.json`) | $0 | 8 s |
| Pi Opus `f69d5c3025b3569c` | 7 / 7 | all 200 | claude-opus-5-5 | `{"type":"adaptive"}` on all 7 | `{"effort":"low"}` on all 7 | 8,937 (4 of 7; call 3 = 8,788) | solved (checker 0) | $0.504 | 2,143 s |
| OpenCode Opus `aa1eaf9c587d64e9` | 0 | none | none | none | none | none | infra: same error | $0 | 7 s |

- **Total spend:** $1.04 for the cells, plus about $0.0001 for the probe.
- **Per-call thinking tokens:**
  - Sonnet: `0 0 361 536 384 482 182 317 138 486 292 274 358 219 158 201 177 99 0 82 321 324 399 401 176 205 108 185 112 60 0 246 245 0`
  - Opus: `33 0 8788 71 0 45 0`
- **Per-call cache:**
  - Sonnet reads: `0 0 0 0 0 9043 9662 ...` (it starts reading only at call 6). Writes for calls 1–5: 3199, 5221, 7468, 8012, 9043.
  - Opus reads: `0 0 3200 0 0 17663 17834`. Writes: `3200 4397 2059 17214 17663 171 769`.
  - The proxy wrote its cache-miss headers to `*.cache-miss-headers.jsonl`.
- **Opus Pi wall time:** about 30 of its 36 minutes went to one of the agent's own CPU-bound `python /tmp/t.py` tool commands. There was no model call during that time.

## Why OpenCode failed (both models)
- The transcript shows `AI_InvalidArgumentError: invalid anthropic provider options` (OpenCode `ba54cee5`). No request reached the proxy, and the ledger is empty.
- The matched config writes `options.thinking = {"type":"between_tools"}`. The bundled OpenCode's Anthropic provider-options check rejects that type before sending.
- This is not the expected `provider_pin_mismatch`, and it is not a server 400. Since nothing was sent, the thinking gate was not tested on this arm.
- **Second issue: the Opus cell asked for Sonnet.** In `data/opencode-harness-smoke/cell.py`, `MODEL_REF` is hardcoded to `anthropic/claude-sonnet-5-5`. So the "Opus" OpenCode cell ran `-m anthropic/claude-sonnet-5-5` with Sonnet's `between_tools` options (`harness_model` = sonnet, `protocol_model` = opus). Even with a working config, its requests would have asked for Sonnet, and `--require-model-match` would have halted the cell.
- Offline at this head, `comparison_config()` with `--matched-config` produces the same Sonnet-only document for either `--vertex-model`: `limit.context` 200000, `options.thinking {type: between_tools}`.

## Gates
1. **Every request traced:** PASS on Pi (34/34, 7/7). Not computable on OpenCode, which sent 0 requests.
2. **Cache read from call 2:** FAIL on Pi for both models. Sonnet read 0 on calls 2–5. Opus read 0 on calls 2, 4 and 5.
3. **Same thinking object on every request, on both arms (fallback gate):** PASS within the Pi arm for both models. Not computable across arms, because OpenCode sent nothing.
4. **Context 200000:** PASS live on Pi for both models (`model_context_window` 200000). OpenCode is offline only: 200000 in the generated config.

## Files
- **Under `raw/`:** the batch log, launcher, probe and analysis scripts, `analysis.json`, the probe ledgers, and per-cell `cmd.json`, `cell.out`, cell record, summary, proxy ledger (jsonl, totals, bytes, cache-miss headers), transcript and workspace tarball.
- **Scrubbing:**
  - Transcripts are `obench/scrub.py` output and pass `--check`.
  - In the other files, `/home/<user>` became `<HOME>` and the VM hostname became `<HOST>`. Commit ids and digests are kept.
  - Workspace tarballs were repacked with numeric owner 0/0.
- **No file is over 50 MB**, so there is no MANIFEST.
