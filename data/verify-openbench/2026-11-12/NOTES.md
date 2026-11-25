# Offline proof, 2026-11-12

Matched Pi vs OpenCode profile is opt-in. Nothing here called a model.

## Approach

`run_ab --matched-config` sets `OBENCH_MATCHED_CONFIG=1` for the process and its cells. Unset, generated configs and Anthropic bodies stay the historical bytes.

While the flag is on, the Vertex proxy writes one thinking setting per model onto every request, on both arms:

- `claude-sonnet-5-5`: `thinking` `{"type":"between_tools"}`, no `output_config`
- `claude-opus-5-5`: `thinking` `{"type":"adaptive"}` plus `output_config` `{"effort":"<level>"}`
- any other model: `thinking` `{"type":"disabled"}`

`--matched-effort` or `OBENCH_MATCHED_EFFORT` selects the Opus level. The default is `low`, the lowest level Opus 5.5 documents. A smoke can set `medium`, `high`, `xhigh`, or `max` without a code change.

Each ledger row stores `thinking_json` and `output_config_json`, the canonical JSON (sorted keys, no spaces) of the objects actually sent upstream, and `thinking_tokens` from `usage.output_tokens_details.thinking_tokens`. Within one model, every traced request must carry the same two byte strings.

## Commands

```bash
python3 -m thesis.ab.run_ab thesis/ab/fixtures/opencode-harness-prs.csv \
  --pr 623 --trials 1 --tasks make-it-run --matched-config --dry-run

python3 -m thesis.ab.run_ab thesis/ab/fixtures/opencode-harness-prs.csv \
  --pr 623 --trials 1 --tasks make-it-run --matched-config --matched-effort high --dry-run
```

`plan-matched.txt` is the first command with fixture SHAs redacted. The added line is `matched-config: context=200000 sonnet=between_tools opus=adaptive effort=low`. `--matched-effort high` changes that line to `effort=high`.
