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
- **Thinking:** unset, so Hermes sends no `thinking` field on the main loop
  and the ledger records `thinking_sent=none`. The ledger also records the raw
  `thinking_type` whenever a `thinking` object was sent, because
  `thinking_sent` folds `disabled` and `between_tools` into `none`.
- **AD1-hermes-beta:** the cell's provider URL ends in
  `/strip-beta/interleaved-thinking-2025-05-14`. The proxy removes that beta
  from Hermes's `anthropic-beta` header before forwarding, on the main loop
  and the title call alike. `fine-grained-tool-streaming-2025-05-14` (tool
  input streaming) is kept. Each ledger row records `beta_stripped`
  (`requested`, `removed`).
- **AD1-hermes-ctx:** `CONTEXT_LENGTH = 200000`, the same window as Codex's
  AD-1 (Researcher decision). It is set explicitly and recorded per cell, with
  a decided status. Hermes's own default for `claude-sonnet-5*` is 1M. Hermes
  keeps its own compaction thresholds: at 200K its 0.50 threshold is floored
  to 0.75, so compaction starts at about 150K tokens.
- **Title side call:** on (stock). Counted in the traces. The proxy tags it
  `side` / `title` (`heuristic:title-schema`): it is the only tool-less call
  whose reply schema (`output_config.format`) has `title` as its sole
  property. Its system prompt ("You name chat sessions…") doesn't match the
  older title regex, and its `max_tokens` is above the short-call limit.
- **Gateway:** every Hermes run starts a gateway daemon. The adapter stops it
  after every cell and removes the per-cell `HERMES_HOME`.

## VM prep (once)

```bash
bash data/hermes-harness-smoke/prep.sh
# prints: export OBENCH_HERMES_ROOT=...   export OBENCH_HERMES_BIN=...
```

`prep.sh` runs Hermes's own installer at the pin
(`scripts/install.sh --commit … --non-interactive`), which brings uv,
Python 3.14, Node, ripgrep and ffmpeg. It then installs the `anthropic` extra,
writes `$ROOT/PIN`, and prints the in-root launcher
`$ROOT/src/.hermes/bin/hermes` as `OBENCH_HERMES_BIN`. Docker cells mount
`OBENCH_HERMES_ROOT` read-only at the same path; a `OBENCH_HERMES_BIN` outside
the root fails the cell before it starts.

**Launch.** The cell does not exec that launcher. Its store Python finds the
dependency environment through `$HERMES_HOME/installs/<key>/facts.json`, and
a fresh per-cell `HERMES_HOME` has none, so it attempts a source-update sync
(which fails on the read-only mount) and runs with no dependencies
(`No module named 'ruamel'`). The adapter instead runs the committed
environment's interpreter on the checkout's entry script,
`<venv>/bin/python $ROOT/src/hermes`, where `<venv>` is
`packages.venv.environment` in `$ROOT/home/installs/<key>/facts.json`
(PM's schema 1; any other shape fails the cell closed), with
`HERMES_DISABLE_LAZY_INSTALLS=1`
(no source-update or sync step at boot). The gateway daemon is spawned with
the same interpreter. `packages.venv.extras` (on the VM: `["all",
"anthropic"]`; `prep.sh`'s installer adds `all`) is recorded in
`harness_settings.launch.extras` and `summary.json` (`hermes_extras`), so the
ledger shows which optional dependencies were installed.

**Prep-time smoke.** `prep.sh` ends by running `hermes --version` and a
dependency import check inside the cell image (`OBENCH_CELL_IMAGE`, default
`h1-env:1027-strace`), with the root mounted read-only, `HOME=/root`, a fresh
`HERMES_HOME` and no network. To re-run only the smoke on an existing install:

```bash
python3 -m obench.adapters.hermes_harness --image h1-env:1027-strace \
  --root "$OBENCH_HERMES_ROOT" --binary "$OBENCH_HERMES_BIN"
```

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
- `hermes_extras`, the venv's installed extras;
- `evidence` and `evidence_pass` for the four checks: traced, `cache_read`
  from main call 2, strict thinking (`thinking_sent=none` and 0 server
  thinking tokens on every call, side calls included), and prompt bytes
  within 5%;
- `2_cache_read` judges main calls only, and lists side calls in `calls`.
  On the Vertex `global` endpoint, a miss on call 2 is often a region split:
  call 2 reads 0 and rewrites the whole prefix, then call 3 reads call 1's
  prefix rather than call 2's. `misses` flags this pattern. OpenCode shows
  it on call 2 in 28 of 90 reference cells, and Pi in 14 of 66
  (`reference_call2_miss`). The pass rule itself is unchanged.
- `server_thinking_tokens_per_call`.

`main_calls`, `aux_calls`, `gateway_stop` and `hermes_extras` come from the
adapter's `harness_settings`, which `run_cell` carries back from the docker
cell.

Raw request bodies, exactly as Hermes sent them, are in
`proxy-ledger/<cell>.requests/`. Any call with `cache_read == 0` appends its
redacted headers to `proxy-ledger/<cell>.cache-miss-headers.jsonl`.
