# Offline proof, 2026-11-12

Matched Pi vs OpenCode profile is opt-in. Nothing here called a model.

## Approach

`run_ab --matched-config` sets `OBENCH_MATCHED_CONFIG=1` for the process and its cells, then restores the previous value. The same environment variable is what `data/pi-harness-smoke/cell.py --matched-config` and `data/opencode-harness-smoke/cell.py --matched-config` set. Unset, generated configs and Anthropic bodies stay the historical bytes.

While the flag is on:

- Pi `models.json` `contextWindow` is 200000 (was 1000000). The command gains `--thinking off`.
- OpenCode comparison config sets `limit.context` to 200000 and `options.thinking` to `{"type": "disabled"}` with no budget. The medium `--variant` is omitted for `claude-opus-5-5`.
- The Vertex proxy rewrites the Anthropic body to `thinking: {"type": "disabled"}` with no budget before it is forwarded. An omitted field does not turn thinking off on these models, so the proxy is what makes the wire explicit for both arms.

Each ledger row stores `thinking_sent` (including `disabled`) and `thinking_tokens`, copied from `usage.output_tokens_details.thinking_tokens`. That field is not `reasoning_tokens` and not the harness `tokens_reasoning` column. Null means the server usage object did not include the field. `proxy_observed` repeats both values per call.

## Commands

```bash
python3 -m thesis.ab.run_ab thesis/ab/fixtures/opencode-harness-prs.csv \
  --pr 623 --trials 1 --tasks make-it-run --dry-run

python3 -m thesis.ab.run_ab thesis/ab/fixtures/opencode-harness-prs.csv \
  --pr 623 --trials 1 --tasks make-it-run --matched-config --dry-run

python3 -m unittest obench.tests.test_matched_config -v
```

Plan text is in `plan-historical.txt` and `plan-matched.txt` with commit SHAs redacted so this directory passes `python3 obench/scrub.py results/verify-openbench/2026-11-12 --check`. The live dry-run printed the real SHAs from the PR fixture; the only added line is `matched-config: context=200000 thinking=disabled`.

`unittest-matched-config.txt` is the 10-test run (historical bytes, 200000 windows, `--thinking off`, explicit disabled request, server `thinking_tokens` distinct from `reasoning_tokens`).

## Live smoke

On every call, both arms, the ledger row must show `thinking_sent=disabled` and `thinking_tokens=0`. `thinking_tokens` is the server usage count. A null value is not a pass. Context window on the Pi settings sidecar is 200000, and the OpenCode model limit context is 200000.

Public Anthropic docs list `thinking.type=disabled` as a 400 on Opus 5.5 (thinking cannot be turned off) and on Sonnet 5.5 (lowest accepted setting is `between_tools`). This change still sends the explicit disabled object the matched config asked for. A 400 or a nonzero `thinking_tokens` will show up on the ledger.
