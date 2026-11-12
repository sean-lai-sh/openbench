# D1 Sonnet prompt follow-up re-smoke at 04521ae5 (2026-11-12)

This is a smoke, not a result. Nothing here is scored or poolable. It re-checks the #243 / #248 runner gates on the D1 prompt-follow-up pair after #248 merged. The 30-per-side run was not launched; it waits for the Researcher to clear this re-smoke.

## Setup
- **Runner:** `04521ae557a04fc3de5256dd1ed40b46ff1c4817` (main after #248). Worktree `~/ob-s248` on thesis-h1-cpu-3.
- **Environment:** thesis-h1-cpu-3, image `h2-env:1022@sha256:72c59033194aae26f6de67c62c77d742aef1d71849000e308f3ee875ff5169ff`, Vertex global, host network, `OBENCH_ADC_METADATA=1`.
- **Pair:** OpenCode PR 725226, without `c436fc69eb039523795555f0ec88d32f20ea3292`, with `d7af1f17056dd4c216b9aa62f03491c6f8fbeeb0`. Prebuilt `build.ts --single` binaries from `/h1/opencode-src/bin/<sha>/` (same hashes as the earlier #243 smoke).
- **Task:** trig-tmpdir, `permissions=workspace`. Seed 1016, 1 trial per side, jobs 2, `--max-cost-usd 3`.
- **Flags:** `--model claude-sonnet-5-5 --vertex-model claude-sonnet-5-5`.
- **Launch:** 2026-11-12 17:12:16 EST. Container `d1fu-resmoke248`. Scripts: `raw/launch-resmoke248.sh`, `raw/cell.sh`. Offline config dump: `raw/config-check.py`. Gate extract: `raw/gate-check.py`.

## Gates (all pass)

| gate | result |
|---|---|
| load_proof: loaded `@ai-sdk/anthropic` equals pin, `pin_source=bundled_package_json` | PASS on both arms |
| every request traced by the proxy and routed upstream to `claude-sonnet-5-5` | PASS (without 1/1, with 3/3) |
| written config `limit.context` 200000 on both arms | PASS (assessed+bound config; live `opencode.json` is not saved in the cell tree, same as #247) |
| thinking unset on both sides | PASS (`thinking_sent` is `none` on every request) |

`run.log` still prints `cell missing required fields ['loaded_anthropic', 'cell_image']` at launch, as it did in the #243 smoke. `loaded_anthropic` stays null on both rows. The load-proof fields that #248 added are the ones that pass: `provider_loaded_version` / `embedded_version` are 3.0.71, equal to `anthropic_pin`, with `pin_source=bundled_package_json`.

## Per cell

Thinking tokens are `usage.output_tokens_details.thinking_tokens` from the proxy ledger, not the row's `tokens_reasoning` (0 on both cells) or `tokens_proxy_reasoning` (null). Cache read/write are `usage.cache_read_input_tokens` and `usage.cache_creation_input_tokens` (same values as the ledger's top-level `cache_read` / `cache_write`).

| arm | sha | binary sha256 | load_proof | loaded / pin / pin_source | requests traced / total | upstream | limit.context | thinking_sent | thinking tokens per call | cache read per call | cache write per call | outcome | spend | wall (ET) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| without | c436fc69 | `38f987cbb2c9bde85c6bd73d965b920298bcc96e2817ee21aac1ef406aa6c667` | pass (`module_hook`: built-in 3.0.71, hook saw no outside copy) | 3.0.71 / 3.0.71 / `bundled_package_json` | 1 / 1 | claude-sonnet-5-5 on the one request; `-m anthropic/claude-sonnet-5-5` | 200000 | `["none"]` | `0` | `0` | `15224` | wrong_answer (score 0; not infra) | $0.0392 | 17:12:36–17:12:46 EST |
| with | d7af1f17 | `162ecbcd445a4d088d6f76100c51d8fa69242ba64e3bf551b1aa160f9abedae0` | pass (`module_hook`: built-in 3.0.71, hook saw no outside copy) | 3.0.71 / 3.0.71 / `bundled_package_json` | 3 / 3 | claude-sonnet-5-5 on every request; `-m anthropic/claude-sonnet-5-5` | 200000 | `["none","none","none"]` | `0, 68, 0` | `0, 0, 0` | `15206, 15586, 15749` | solved (score 1.0) | $0.1211 | 17:12:40–17:12:55 EST |

- **Total spend:** $0.1604. Under the $3 smoke cap.
- **Toolchain** on both sides (also `raw/725226/*.toolchain.json`): `ai 6.0.168`, `anthropic 3.0.71`, `bun 1.3.13`.
- **Cache:** the with arm (`d7af1f17`) never read from cache (reads `[0, 0, 0]`, writes `[15206, 15586, 15749]`). The without arm wrote `15224` on its single call (read `0`); a call-2 read was not possible there. Dollar costs are in the cache cost gap section below.
- **Thinking still arrives from the server** on the with arm (68 thinking tokens on call 2) even though no thinking parameter was sent. Same pattern as the #243 smoke and earlier D1 Sonnet rows. Do not use `tokens_reasoning` for this count.
- **Written config evidence** (`config-check.txt`, `raw/config-check.json`): assessment of each prebuilt binary still produces an Opus entry with `limit.context` 1,000,000. `bind_opencode_model(..., "claude-sonnet-5-5")` renames it and sets `limit.context` 200000 (output stays 128000) on both arms. `pin_source` and the 3.0.71 pin are attached by `_decorate_toolchain` from `packages/opencode/package.json` at the binary's commit.


## Cache cost gap

Spend uses the same Standard global list as `proxy_cost_usd` / `requests_cost_usd`: Claude Sonnet 5.5 rates in `thesis/ab/vertex_list_prices.json` (read 2026-10-29). USD per million tokens: uncached input $2.00, output $10.00, 5-minute cache write $2.50, cache read $0.10. Cache writes in this run are all `ephemeral_5m`. The components below sum to the recorded spend ($0.039218 without, $0.1211485 with).

| arm | cache read tokens | cache read $ | cache write tokens | cache write $ | total spend |
|---|---|---|---|---|---|
| without (`c436fc69`) | 0 | $0.000000 | 15224 | $0.038060 | $0.039218 |
| with (`d7af1f17`) | 0 (`[0, 0, 0]`) | $0.000000 | 46541 (`[15206, 15586, 15749]`) | $0.1163525 | $0.1211485 |

Per-call total cost, with the same rates:

| arm / call | uncached input | output | cache write $ | cache read $ | total $ |
|---|---|---|---|---|---|
| without call 1 | 4 / $0.000008 | 115 / $0.001150 | $0.038060 | $0.000000 | $0.039218 |
| with call 1 | 4 / $0.000008 | 89 / $0.000890 | $0.038015 | $0.000000 | $0.038913 |
| with call 2 | 2 / $0.000004 | 215 / $0.002150 | $0.038965 | $0.000000 | $0.041119 |
| with call 3 | 2 / $0.000004 | 174 / $0.001740 | $0.0393725 | $0.000000 | $0.0411165 |
| with sum | 8 / $0.000016 | 478 / $0.004780 | $0.1163525 | $0.000000 | $0.1211485 |

The with arm writes cache every call and never reads, so it pays the 5-minute write rate three times and gets no cache-hit credit. That raises its cost (cache writes are $0.1163525 of $0.1211485, versus $0.038060 of $0.039218 on the without arm's single write of 15224) and may also raise latency versus without.

## Files
- **Under `raw/`:** launcher, cell script, dry-run, run log, driver log, config-check and gate-check scripts and outputs, `prs.csv`, `task-map.csv`, per-arm jsonl / toolchain / cell json, proxy ledgers (jsonl, totals, bytes, cache-miss headers), transcripts, evidence dirs, and workspace tarballs.
- **Scrubbing:**
  - Transcript `.txt` files (and the other text files under `transcripts/`) are `obench/scrub.py` output and pass `--check` (exit 0).
  - A tree-wide `--check` on `transcripts/` also reports 3 `[base64-blob]` hits in `with/trig-tmpdir/1/opencode-default.db-wal`. Those are signed thinking blocks in the OpenCode session WAL, the same class of hit noted in the #243 smoke README. The WAL was left as the original binary; it was not rewritten by the scrubber.
  - In the other files, `/home/box` became `<HOME>` and the VM hostname became `<HOST>`. Commit ids and digests are kept.
  - Workspace tarballs were repacked with numeric owner 0/0.
- **No file is over 50 MB**, so there is no MANIFEST.

The original unscrubbed run remains on thesis-h1-cpu-3 at `~/h2/d1fu-resmoke248-1112`. Nothing was deleted.
