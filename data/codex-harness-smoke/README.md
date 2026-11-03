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
