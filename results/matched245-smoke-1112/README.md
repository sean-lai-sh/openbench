# PR #245 matched-config live smoke (2026-11-12): FAILED, both models reject `thinking.type=disabled`

Not a result. Failed smoke, stored as evidence. Not scored, not poolable.

- Head run: `ee6f8a405bb74de3b7f55870d94da1df9d5f3546` (PR #245, branch `cursor/matched-pair-200k-thinking-off-0811`).
  The later head `d11672d6b44431c5ef911468ae9229b75267e6d3` differs from it only in `.gitignore` (no code change).
- VM: thesis-h1-cpu-2 (us-central1-a), image `h1-env:1027-strace`, Vertex global endpoint, `--require-model-match`, bridge network.
- Launch: `m245-launch.sh` -> `m245-batch.py` (same pattern as `results/pi-vs-oc-180-1029/pvo-batch.py`; Pi's `TASK`
  is set on the loaded module, no repo code edited). Every cell passes `--matched-config` (`OBENCH_MATCHED_CONFIG=1`).
- Plan: regex-chess (#196: Pi 5-10 calls/cell, OpenCode 4-11), one model at a time, Pi then OpenCode, Sonnet 5.5 then Opus 5.5,
  $6 total cap, stop a model's cells on any HTTP 400.

## What happened

Both models returned HTTP 400 on the first request of the Pi cell. The proxy had rewritten `thinking` to `{"type":"disabled"}`
(ledger `thinking_sent=disabled`). No tokens were billed (spend $0.00). The OpenCode cells were not launched for either model.

| model | cell | calls | traced | status | upstream_model | thinking_sent | thinking_tokens | outcome | wall |
|---|---|---|---|---|---|---|---|---|---|
| claude-sonnet-5-5 | Pi `30c611402d068caa` | 1 | 1/1 | 400 | claude-sonnet-5-5 | disabled | null | infra (no model output) | 6 s |
| claude-sonnet-5-5 | OpenCode | - | - | not run (stop on 400) | | | | | |
| claude-opus-5-5 | Pi `4197498f074e92ef` | 1 | 1/1 | 400 | claude-opus-5-5 | disabled | null | infra (no model output) | 5 s |
| claude-opus-5-5 | OpenCode | - | - | not run (stop on 400) | | | | | |

400 bodies (verbatim from the proxy ledger):

- Sonnet 5.5: `To turn thinking off on this model, send "thinking": {"type": "between_tools"} instead of {"type": "disabled"}. The model does not think before responding. The short updates it writes between tool calls come back as thinking blocks.` (request_id `req_vrtx_011CgyhLDYZRPnHujW93jZbW`)
- Opus 5.5: `"thinking.type.disabled" is not supported for this model. Use "thinking.type.adaptive" and "output_config.effort" to control thinking behavior.` (request_id `req_vrtx_011CgyhLauBv7su47XdALK1R`)

Gate 2 (cache) and gate 3 (zero thinking tokens) could not be measured: no call succeeded.
Gate 4 was not observable in the live artifacts (Pi's models.json lives in the cell temp dir; Pi's transcript shows `thinkingLevel: "off"`).
`gate4-offline-configs.txt` is the PR's own generators at this head, no model calls: Pi `contextWindow` 200000 for both models
(`forceAdaptiveThinking: true` still set in compat), OpenCode `limit.context` 200000 with `options.thinking {type: disabled}`.

## Fallback

The Researcher's fallback (lowest accepted setting, sent identically on both arms) needs a code change at this head:
`thesis/ab/vertex_anthropic_proxy.py` hardcodes `DISABLED_THINKING = {"type": "disabled"}` in `apply_disabled_thinking`,
with no env or flag to choose another object, and `classify_thinking` labels any other type `none`. So no fallback was run.

## Files

- `raw/` batch log, launcher, per-cell `cmd.json`, `cell.out`, cell record, summary, proxy ledger (`.jsonl`, `.totals.json`, `.bytes`), transcript.
- Transcripts are `obench/scrub.py` output and pass `scrub.py --check`. In the other files `/home/<user>` -> `<HOME>` and the VM
  hostname -> `<HOST>`; commit ids and digests are kept. The two `*.workspace.tar.gz` (only the task's `check.py`) are omitted.
  No file is over 50 MB, so there is no MANIFEST.
