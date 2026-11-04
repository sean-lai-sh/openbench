# Hermes hard-suite cell (Stage 4)

One local cell of the Hermes arm, on the same path as the Pi, OpenCode and
Codex arms: the shared Vertex proxy (per-cell ledger, `--require-model-match`),
`obench.run.run_cell`, and the cell row with the proxy trace, the
ledger-priced cost and the four-check evidence. Hermes speaks Anthropic
Messages natively, so it talks to the proxy's `POST /v1/messages` with no
translation. The adapter is `obench/adapters/hermes_harness.py`.

- **Pin:** NousResearch/hermes-agent `4dcef215cfe41bd2d02c2d1dad6e257a18101216`
  (MIT). It has no tag of its own; it is 533 commits after `v0.22.5` and an
  ancestor of `v0.22.6`. The cell fails closed if the install's `PIN` stamp
  differs.
- **Gating:** `OBENCH_HERMES_HARNESS=1` plus `OBENCH_VERTEX_PROXY_URL`. With the
  flag on and no URL, the cell fails before any process starts. With the flag
  off, the cell runs stock Hermes and is never proxied.
- **Thinking:** unset, so Hermes sends no `thinking` field and the ledger
  records `thinking_sent=none`, matching OpenCode. Server-side thinking tokens
  are recorded separately in the evidence.
- **Context length:** `CONTEXT_LENGTH = 1000000`, set explicitly and recorded
  per cell. **Pending the Researcher's call:** 1M for Pi and stock Hermes, or
  200K as in Codex's AD-1.
- **Title side call:** on (stock). It is tagged `side` at the proxy and counted
  in the traces.
- **Gateway:** every Hermes run starts a gateway daemon. The adapter stops it
  after every cell and removes the per-cell `HERMES_HOME`.

## VM prep (once)

```bash
bash data/hermes-harness-smoke/prep.sh
# prints: export OBENCH_HERMES_ROOT=...   export OBENCH_HERMES_BIN=...
```

`prep.sh` runs Hermes's own installer at the pin
(`scripts/install.sh --commit … --non-interactive`), which brings uv,
Python 3.14, Node, ripgrep and ffmpeg. It then installs the `anthropic` extra
and writes `$ROOT/PIN`. Docker cells mount `OBENCH_HERMES_ROOT` read-only at
the same path.

## Run the one smoke cell

```bash
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}" GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:?}"
export OBENCH_HERMES_ROOT=... OBENCH_HERMES_BIN=...      # from prep.sh
python3 data/hermes-harness-smoke/cell.py \
  --out "$HOME/hermes-harness-smoke" \
  --exec docker --image "${OBENCH_CELL_IMAGE:-h1-env:1027-strace}"
```

`--out` must be outside every `results/` and `data/` directory. `summary.json`
holds:

- the token split and `proxy_cost_usd`;
- `main_calls` and `aux_calls`, from Hermes's `--usage-file`;
- `gateway_stop`, showing how the daemon was stopped;
- `evidence` and `evidence_pass` for the four checks: traced, `cache_read`
  from call 2, `thinking_sent` vs OpenCode, and prompt bytes within 5%;
- `server_thinking_tokens_per_call`.

Raw request bodies, exactly as Hermes sent them, are in
`proxy-ledger/<cell>.requests/`. Any call with `cache_read == 0` appends its
redacted headers to `proxy-ledger/<cell>.cache-miss-headers.jsonl`.
