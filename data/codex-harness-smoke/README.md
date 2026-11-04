# Codex hard-suite cell (Stage 4)

One local cell of the Codex arm, on the same path as the Pi and OpenCode arms
from #196: the shared Vertex proxy (per-cell ledger, `--require-model-match`),
`obench.run.run_cell`, and the cell row with the proxy trace and ledger-priced
cost. Codex reaches Claude on Vertex through the proxy's `POST /v1/responses`
endpoint (`thesis/ab/responses_api.py`). The adapter is
`obench/adapters/codex_harness.py`.

- **Pin:** Codex CLI `0.144.5` (`rust-v0.144.5`, Apache-2.0). The cell fails
  closed if `codex --version` reports anything else.
- **AD-1:** `model_context_window=200000` (AD1-codex-ctx). No `apply_patch`
  is added (AD1-codex-edit): stock Codex on a Claude id edits through the
  shell.
- **Isolation:** `CODEX_HOME` is a fresh empty directory. The custom provider
  needs no OpenAI login; its key is a placeholder the proxy ignores.

## Get the pinned binary (on the VM)

```bash
mkdir -p ~/h1/codex/0.144.5 && cd ~/h1/codex/0.144.5
curl -fsSLO https://github.com/openai/codex/releases/download/rust-v0.144.5/codex-x86_64-unknown-linux-musl.tar.gz
tar -xzf codex-x86_64-unknown-linux-musl.tar.gz
mv codex-x86_64-unknown-linux-musl codex && chmod +x codex
./codex --version   # must print codex-cli 0.144.5
```

The release binary is static, so docker cells mount its directory at
`/opt/openbench-codex` and the cell image needs neither Codex nor Node.

## Run the one smoke cell

Requires `GOOGLE_CLOUD_PROJECT` (or `GCLOUD_PROJECT`) and Application Default
Credentials, like the other two arms. `--out` must be outside every `results/`
and `data/` directory; the launcher refuses otherwise.

```bash
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
export GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:?}"
python3 data/codex-harness-smoke/cell.py \
  --out "$HOME/codex-harness-smoke" \
  --binary "$HOME/h1/codex/0.144.5/codex" \
  --exec docker --image "${OBENCH_CELL_IMAGE:-h1-env:1027-strace}"
```

It prints `proxy-reached cell=<id> reached=yes calls=<n>` and a one-line JSON
summary with the ledger token split (`input_uncached`, `output`,
`cache_read`, `cache_write`) and `proxy_cost_usd`. The full row is in
`<out>/claude-sonnet-5-5.json`.

## Re-smoke evidence (four criteria)

`summary.json` has an `evidence` block per cell, and `evidence_pass` with one
boolean per criterion. `smoke.log` gets the same booleans on one
`evidence {...}` line.

1. **`1_traced`:** `trace_requests` equals the ledger request count, and
   `untraced_requests` is 0. Codex model calls are counted from its session
   rollout's `token_count` events.
2. **`2_cache_read`:** `cache_read` for each call. The criterion passes when
   every call from the second one on reads more than 0 tokens.
3. **`3_thinking_sent`:** the Codex `thinking_sent` values next to each
   reference arm's values for the same model, read from the committed #196
   ledgers. It passes against **OpenCode**, the Researcher's thinking
   reference. For Sonnet 5.5, OpenCode recorded `none` and Pi recorded
   `adaptive`; Pi is listed for context only. Codex on Claude sends no
   thinking.
4. **`4_prompt_bytes`:** for each call, the system and tool bytes the proxy
   forwarded, the bytes Codex itself sent, and the relative difference. The
   tolerance is 5%.

Evidence files in `<out>/proxy-ledger/`:

- `<cell>.responses/NNNN.request.json`: every raw `/v1/responses` body,
  exactly as Codex 0.144.5 sent it, before translation. Use these to count
  the real Codex system and tool bytes.
- `<cell>.cache-miss-headers.jsonl`: one line per call with `cache_read == 0`.
  It holds the request headers and the upstream headers (credentials
  redacted), the token usage, and the matching raw-body file.
