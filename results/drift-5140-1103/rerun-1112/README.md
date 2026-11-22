# Opus 5140 drift rerun resumed 2026-11-12 (rerun-1112)

**Status: the 9 rerun slots are done and included.** The earlier PROVISIONAL flag (pending those reruns) is lifted; this head still needs the Researcher's review before merge.

Stored beside the earlier 2026-11-03 partial data in `results/drift-5140-1103/` (not overwritten).
180/180 cells (with/without, 90 each): 171 from the 2026-11-12 session plus 9 slot reruns finished 2026-11-13 00:08–00:46 ET. Everything was on the same VM (`thesis-h1-cpu`), runner head `b1cbded32a92`, `@ai-sdk/anthropic` pin `2.0.50`, image `h2-env:1022`, and `cell.sh`. The 11/12 session ran with STOPAT $300 (never reached) and driver exit 0.
Transcripts scrubbed with `obench/scrub.py` (`--check` clean on `opus/`, `excluded-1103/opus/` and the logs; the only `--check` hits are the sha256 columns of the two MANIFEST files, which stay flagged by design). The four provenance hash fields and the hex segment of `binary_path` in the cell JSON and jsonl were restored after scrubbing; see "Provenance hashes restored" below. Workspace tarballs are NOT committed. `MANIFEST.txt` lists the 180 in-tally tarballs (size + sha256), and the originals remain on VM `thesis-h1-cpu` under `~/h2/drift-5140-1103/opus`.
Tracing: the proxy ledger is the trace of record, but some requests are untraced (title calls). `untraced_requests` is 170 of 1,339 requests, across 149 of the 180 cells.

## Provenance hashes restored (Codex P2)

The scrub had replaced the provenance hashes in every cell record and jsonl row with `<REDACTED_HEX>`. That hid which binary each arm ran and made the data impossible to check against `MANIFEST.txt`. These are content hashes and commit ids, not personal data, so they were restored from the raw, unscrubbed cells on VM `thesis-h1-cpu` (`~/h2/drift-5140-1103/opus` and `~/h2/drift-5140-1103/excluded-1103/opus`). Restored fields: `binary_sha256`, `runner_commit`, `lockfile_sha256`, `final_workspace_tar_sha256`, and the hex path segment of `binary_path`. Restored in all 189 cell JSON files (180 in tally under `opus/`, 9 under `excluded-1103/opus/`) and all 189 jsonl rows (`opus/5140/{with,without}.jsonl`, `excluded-1103/opus/5140/{with,without}.jsonl`). No other field changed. The hex inside `cmd`, `harness_version`, `cell_image` and `provider_pin_sha256` is still redacted, along with the per-file `sha256` values under `checker_workspace_files`.

| Arm | `binary_sha256` | `binary_path` | Cells |
|---|---|---|---|
| with | `2aeae8457f8e…` | `/h1/opencode-src/bin/75a4dcbce833…/opencode` | 94 (90 + 4 excluded) |
| without | `24c7c44c841d…` | `/h1/opencode-src/bin/3a179fcd34ae…/opencode` | 95 (90 + 5 excluded) |

(Prefixes shown here; the full values are in the cell files, and free text in this README would be flagged by `--check`.) All cells share `runner_commit` `b1cbded32a92…` and `lockfile_sha256` `ef8af7527908…`. **MANIFEST check:** every `final_workspace_tar_sha256` (and `final_workspace_tar_bytes`) matches its tarball's MANIFEST line: 180/180 against `MANIFEST.txt` and 9/9 against `excluded-1103/MANIFEST.txt`, with no mismatches. The 9 excluded cells still record their original `final_workspace_tar` path under `opus/`, because that field was left unchanged. Their tarballs now live under `excluded-1103/opus/` on the VM.

`obench/scrub.py` now has a field-scoped exception so these values pass `--check`. It applies only in `.json`/`.jsonl` files, only as the exact string value of those five keys (for `binary_path`, only a path segment that is exactly hex), and only for an exact 40-hex or 64-hex value. The same value under any other key, in an escaped/free-text string, or in any other file type is still flagged (`obench/tests/test_scrub.py::TestProvenanceHexException`). There is no directory-wide hex allow.

## Location under `results/` (Codex P1 accepted)

`AGENTS.md` reserves `results/` for gitignored scratch, and committed data belongs under `data/`. The parent `results/drift-5140-1103/` (the 2026-11-03 partial) is already on `main`, so this PR keeps the dataset together there rather than splitting it across two trees. A follow-up PR will move the whole `results/drift-5140-1103/` tree to `data/` with a plain `git mv` and no history rewrite.

## 2026-11-03 partial cells: excluded, then rerun

Nine cells in the 11/12 output tree (4 with, 5 without) had `ended_et` 2026-11-03. They were the partial #239 cells, which the resumed driver skipped instead of rerunning, and they had been counted inside the earlier 39/90 vs 44/90 (1/4 vs 2/5 solved). They are now in `excluded-1103/` (cells, transcripts, side jsonl, 13 proxy-ledger triples dated 11/03, and their own `MANIFEST.txt`) and are **excluded from every tally**. The same files were moved on the VM to `~/h2/drift-5140-1103/excluded-1103/`.

| Slot | 2026-11-03 result (excluded) | 2026-11-13 rerun (in tally) |
|---|---|---|
| with/dna-insert/1 | wrong_answer | infra (thinking-signature 400) |
| with/filter-js-from-html/1 | solved | solved |
| with/model-extraction-relu-logits/1 | timeout | solved |
| with/polyglot-rust-c/1 | wrong_answer | wrong_answer |
| without/dna-insert/1 | wrong_answer | infra (thinking-signature 400) |
| without/filter-js-from-html/1 | wrong_answer | solved |
| without/model-extraction-relu-logits/1 | solved | solved |
| without/polyglot-rust-c/1 | wrong_answer | wrong_answer |
| without/regex-chess/1 | solved | solved |

The reruns used `--cells` with the same seeded order (`interleave-seeded`, seed 1022), so trial ids and cell keys match a full run. Driver: `rerun1103-driver.sh` (refuses a dirty worktree, a wrong head or a wrong image digest; $15 stop, never reached). Logs: `rerun1103-driver.log`, `rerun1103-spend.log`, `container-rerun1103.log`, `opus/run-rerun1103.log` (the 11/12 runner log is `opus/run-1112.log`). Rerun spend was **$4.14** (sum of `requests_cost_usd` over the 9 cells). All 9 have `load_proof=pass` and loaded pin `2.0.50`.

## Results

Recomputed from `opus/5140/with.jsonl` and `opus/5140/without.jsonl` (stored `score==1` numerators). Fisher tests are two-sided. No cell was reclassified.

| Cut | with | without | two-sided Fisher p |
|---|---|---|---|
| **Headline: 11/12 run + 9 reruns, dna-insert excluded** | **40/80** | **45/80** | **0.5264 (≈.53)** |
| Raw: all 180 (11/12 run + 9 reruns) | 40/90 | 45/90 | 0.5505 (≈.55) |
| 11/12 run + 9 reruns, dna-insert included | 40/90 | 45/90 | 0.5505 (≈.55) |

No drift effect. After the reruns, every in-tally cell comes from the 11/12 session or its 9 reruns, so the "today-only, dna-insert included" cut is the same 180 cells as raw.

For reference, before the reruns (171 cells from 11/12 only, with the 9 slots missing): 38/86 vs 42/85 (p=0.5413), and with dna-insert excluded 38/77 vs 42/76 (p=0.5187). The superseded mixed figure of 39/90 vs 44/90 (p=.55) included the 9 cells from 11/03 and should not be used.

### dna-insert: excluded (harness/API error)

19 of the 20 dna-insert cells (10 with, 9 without) fail with a 400 `invalid_request_error`: `Invalid signature in thinking block. The block is bound to a different conversation.` That is 17 of the 18 cells from 11/12 plus both trial-1 reruns. The only other cell, without/dna-insert/8 (wrong_answer), failed for a different reason. The model never gets a turn to fail, and it happens on both arms. This is a harness/API problem (replayed thinking-block signature), not an agent failure, so the task is **excluded** rather than scored as unsolved. **dna-insert stays excluded until the thinking-block binding is fixed.** The 400 body names `thinking.block_binding.prefix_mismatch_behavior` / the `thinking-binding-controls-2026-08-01` beta as the API-side control.

## Infra cells (22): cause breakdown

Stored `failure_class=infra`: 13 with, 9 without. Counts below use that stored label. `env_failure` is false on all 22.

### Harness/API thinking-signature 400 — 19 cells (10 with, 9 without), all dna-insert

Each cell JSON has `ledger_statuses: [400]` and `failure_reason` / `provider_error` equal to the Anthropic `invalid_request_error` quoted above. Wall time is 9–24s; the checker then reports `missing primers.fasta`. `without/dna-insert/6` fails at `messages.1.content.4`; the rest fail at `messages.1.content.2`.

| Cell | Arm | Trial | Cause | Citation |
|---|---|---|---|---|
| with/dna-insert/1 (rerun 2026-11-13) | with | 1 | `invalid_request_error` (thinking signature) | `opus/5140/cells/with/dna-insert/1.json` fields `failure_reason`, `provider_error`, `ledger_statuses=[400]` (messages.1.content.2) |
| with/dna-insert/2 | with | 2 | `invalid_request_error` (thinking signature) | `opus/5140/cells/with/dna-insert/2.json` fields `failure_reason`, `provider_error`, `ledger_statuses=[400]` (messages.1.content.2) |
| with/dna-insert/3 | with | 3 | `invalid_request_error` (thinking signature) | `opus/5140/cells/with/dna-insert/3.json` fields `failure_reason`, `provider_error`, `ledger_statuses=[400]` (messages.1.content.2) |
| with/dna-insert/4 | with | 4 | `invalid_request_error` (thinking signature) | `opus/5140/cells/with/dna-insert/4.json` fields `failure_reason`, `provider_error`, `ledger_statuses=[400]` (messages.1.content.2) |
| with/dna-insert/5 | with | 5 | `invalid_request_error` (thinking signature) | `opus/5140/cells/with/dna-insert/5.json` fields `failure_reason`, `provider_error`, `ledger_statuses=[400]` (messages.1.content.2) |
| with/dna-insert/6 | with | 6 | `invalid_request_error` (thinking signature) | `opus/5140/cells/with/dna-insert/6.json` fields `failure_reason`, `provider_error`, `ledger_statuses=[400]` (messages.1.content.2) |
| with/dna-insert/7 | with | 7 | `invalid_request_error` (thinking signature) | `opus/5140/cells/with/dna-insert/7.json` fields `failure_reason`, `provider_error`, `ledger_statuses=[400]` (messages.1.content.2) |
| with/dna-insert/8 | with | 8 | `invalid_request_error` (thinking signature) | `opus/5140/cells/with/dna-insert/8.json` fields `failure_reason`, `provider_error`, `ledger_statuses=[400]` (messages.1.content.2) |
| with/dna-insert/9 | with | 9 | `invalid_request_error` (thinking signature) | `opus/5140/cells/with/dna-insert/9.json` fields `failure_reason`, `provider_error`, `ledger_statuses=[400]` (messages.1.content.2) |
| with/dna-insert/10 | with | 10 | `invalid_request_error` (thinking signature) | `opus/5140/cells/with/dna-insert/10.json` fields `failure_reason`, `provider_error`, `ledger_statuses=[400]` (messages.1.content.2) |
| without/dna-insert/1 (rerun 2026-11-13) | without | 1 | `invalid_request_error` (thinking signature) | `opus/5140/cells/without/dna-insert/1.json` fields `failure_reason`, `provider_error`, `ledger_statuses=[400]` (messages.1.content.2) |
| without/dna-insert/2 | without | 2 | `invalid_request_error` (thinking signature) | `opus/5140/cells/without/dna-insert/2.json` fields `failure_reason`, `provider_error`, `ledger_statuses=[400]` (messages.1.content.2) |
| without/dna-insert/3 | without | 3 | `invalid_request_error` (thinking signature) | `opus/5140/cells/without/dna-insert/3.json` fields `failure_reason`, `provider_error`, `ledger_statuses=[400]` (messages.1.content.2) |
| without/dna-insert/4 | without | 4 | `invalid_request_error` (thinking signature) | `opus/5140/cells/without/dna-insert/4.json` fields `failure_reason`, `provider_error`, `ledger_statuses=[400]` (messages.1.content.2) |
| without/dna-insert/5 | without | 5 | `invalid_request_error` (thinking signature) | `opus/5140/cells/without/dna-insert/5.json` fields `failure_reason`, `provider_error`, `ledger_statuses=[400]` (messages.1.content.2) |
| without/dna-insert/6 | without | 6 | `invalid_request_error` (thinking signature) | `opus/5140/cells/without/dna-insert/6.json` fields `failure_reason`, `provider_error`, `ledger_statuses=[400]` (messages.1.content.4) |
| without/dna-insert/7 | without | 7 | `invalid_request_error` (thinking signature) | `opus/5140/cells/without/dna-insert/7.json` fields `failure_reason`, `provider_error`, `ledger_statuses=[400]` (messages.1.content.2) |
| without/dna-insert/9 | without | 9 | `invalid_request_error` (thinking signature) | `opus/5140/cells/without/dna-insert/9.json` fields `failure_reason`, `provider_error`, `ledger_statuses=[400]` (messages.1.content.2) |
| without/dna-insert/10 | without | 10 | `invalid_request_error` (thinking signature) | `opus/5140/cells/without/dna-insert/10.json` fields `failure_reason`, `provider_error`, `ledger_statuses=[400]` (messages.1.content.2) |

### Stored infra, wall-time capped — 3 cells (with only); not environment

`with/sam-cell-seg` trials 1, 3 and 4 are stored `failure_class=infra` and are wall-time capped (`error: timeout after 2400s`, wall time ≈2404s). None has a `failure_reason`, a `provider_error`, or a ledger 400. `agent-output.txt` has no `invalid_request_error` and no container/network/image/disk/ENOENT failure that ends the cell. The agent did real work (12–22 proxy requests, 13k–22k output tokens), then went idle (server heartbeat lines only) until the 2400s cap; the checker ran afterward and failed a unit test. **`with/sam-cell-seg/7` has the same shape (`timeout after 2400s`, 2403.7s) but is stored as `timeout`, not infra.** That inconsistency is noted here; no cell was reclassified. None of these is treated as environment-caused. Timestamps in `agent-output.txt` are UTC; times below are America/New_York (ET, UTC-5).

| Cell | Arm | Trial | Cause | Citation |
|---|---|---|---|---|
| with/sam-cell-seg/1 | with | 1 | stored infra; committed logs show wall-time timeout after idle | `opus/5140/cells/with/sam-cell-seg/1.json` cell JSON `error: timeout after 2400s`; `transcripts/with/sam-cell-seg/1/agent-output.txt` last model work L593 at 15:24:57 ET, then heartbeat-only through L633 at 15:50:00 ET (start 15:11:29 ET) |
| with/sam-cell-seg/3 | with | 3 | stored infra; committed logs show wall-time timeout after idle | `opus/5140/cells/with/sam-cell-seg/3.json` cell JSON `error: timeout after 2400s`; `transcripts/with/sam-cell-seg/3/agent-output.txt` last model work L651 at 16:50:01 ET, then heartbeat-only until 17:25:14 ET (start 16:45:44 ET) |
| with/sam-cell-seg/4 | with | 4 | stored infra; committed logs show wall-time timeout after idle | `opus/5140/cells/with/sam-cell-seg/4.json` cell JSON `error: timeout after 2400s`; `transcripts/with/sam-cell-seg/4/agent-output.txt` last model work L309 at 17:38:58 ET, then heartbeat-only until 18:13:34 ET (start 17:36:03 ET) |

### Environment-caused infra — 0 cells

No cell among these 22 has `env_failure=true` or an environment marker (container, network, image, disk, ENOENT) as the cause. Every cell records `cell_image` as the pinned `h2-env:1022` image (digest redacted in the committed files).

## Per-cell load_proof and loaded pin

Read from the committed per-cell rows in `opus/5140/with.jsonl` and `opus/5140/without.jsonl` (same fields as `opus/5140/cells/{arm}/{task}/{trial}.json`). **All 180 in-tally cells, including the 9 reruns, have `load_proof=pass`.** None is missing `load_proof`. The loaded pin/version is `2.0.50` on every cell (`loaded_anthropic`, also `anthropic_pin` and `provider_loaded_version`; `load_proof_basis=user_agent`, `load_proof_reason=User-Agent 2.0.50`, `provider_version_proven=true`). The recorded `cell_image` is `h2-env:1022@sha256:<REDACTED_HEX>` on every cell; `obench/scrub.py` redacted the digest, and it is not reconstructed here. The trial-1 rows for the 9 rerun slots listed above are the 2026-11-13 rerun cells.

| Cell id | Arm | Trial | load_proof | Loaded pin/version |
|---|---|---|---|---|
| with/dna-insert/1 | with | 1 | pass | 2.0.50 |
| with/dna-insert/2 | with | 2 | pass | 2.0.50 |
| with/dna-insert/3 | with | 3 | pass | 2.0.50 |
| with/dna-insert/4 | with | 4 | pass | 2.0.50 |
| with/dna-insert/5 | with | 5 | pass | 2.0.50 |
| with/dna-insert/6 | with | 6 | pass | 2.0.50 |
| with/dna-insert/7 | with | 7 | pass | 2.0.50 |
| with/dna-insert/8 | with | 8 | pass | 2.0.50 |
| with/dna-insert/9 | with | 9 | pass | 2.0.50 |
| with/dna-insert/10 | with | 10 | pass | 2.0.50 |
| with/filter-js-from-html/1 | with | 1 | pass | 2.0.50 |
| with/filter-js-from-html/2 | with | 2 | pass | 2.0.50 |
| with/filter-js-from-html/3 | with | 3 | pass | 2.0.50 |
| with/filter-js-from-html/4 | with | 4 | pass | 2.0.50 |
| with/filter-js-from-html/5 | with | 5 | pass | 2.0.50 |
| with/filter-js-from-html/6 | with | 6 | pass | 2.0.50 |
| with/filter-js-from-html/7 | with | 7 | pass | 2.0.50 |
| with/filter-js-from-html/8 | with | 8 | pass | 2.0.50 |
| with/filter-js-from-html/9 | with | 9 | pass | 2.0.50 |
| with/filter-js-from-html/10 | with | 10 | pass | 2.0.50 |
| with/model-extraction-relu-logits/1 | with | 1 | pass | 2.0.50 |
| with/model-extraction-relu-logits/2 | with | 2 | pass | 2.0.50 |
| with/model-extraction-relu-logits/3 | with | 3 | pass | 2.0.50 |
| with/model-extraction-relu-logits/4 | with | 4 | pass | 2.0.50 |
| with/model-extraction-relu-logits/5 | with | 5 | pass | 2.0.50 |
| with/model-extraction-relu-logits/6 | with | 6 | pass | 2.0.50 |
| with/model-extraction-relu-logits/7 | with | 7 | pass | 2.0.50 |
| with/model-extraction-relu-logits/8 | with | 8 | pass | 2.0.50 |
| with/model-extraction-relu-logits/9 | with | 9 | pass | 2.0.50 |
| with/model-extraction-relu-logits/10 | with | 10 | pass | 2.0.50 |
| with/polyglot-rust-c/1 | with | 1 | pass | 2.0.50 |
| with/polyglot-rust-c/2 | with | 2 | pass | 2.0.50 |
| with/polyglot-rust-c/3 | with | 3 | pass | 2.0.50 |
| with/polyglot-rust-c/4 | with | 4 | pass | 2.0.50 |
| with/polyglot-rust-c/5 | with | 5 | pass | 2.0.50 |
| with/polyglot-rust-c/6 | with | 6 | pass | 2.0.50 |
| with/polyglot-rust-c/7 | with | 7 | pass | 2.0.50 |
| with/polyglot-rust-c/8 | with | 8 | pass | 2.0.50 |
| with/polyglot-rust-c/9 | with | 9 | pass | 2.0.50 |
| with/polyglot-rust-c/10 | with | 10 | pass | 2.0.50 |
| with/regex-chess/1 | with | 1 | pass | 2.0.50 |
| with/regex-chess/2 | with | 2 | pass | 2.0.50 |
| with/regex-chess/3 | with | 3 | pass | 2.0.50 |
| with/regex-chess/4 | with | 4 | pass | 2.0.50 |
| with/regex-chess/5 | with | 5 | pass | 2.0.50 |
| with/regex-chess/6 | with | 6 | pass | 2.0.50 |
| with/regex-chess/7 | with | 7 | pass | 2.0.50 |
| with/regex-chess/8 | with | 8 | pass | 2.0.50 |
| with/regex-chess/9 | with | 9 | pass | 2.0.50 |
| with/regex-chess/10 | with | 10 | pass | 2.0.50 |
| with/sam-cell-seg/1 | with | 1 | pass | 2.0.50 |
| with/sam-cell-seg/2 | with | 2 | pass | 2.0.50 |
| with/sam-cell-seg/3 | with | 3 | pass | 2.0.50 |
| with/sam-cell-seg/4 | with | 4 | pass | 2.0.50 |
| with/sam-cell-seg/5 | with | 5 | pass | 2.0.50 |
| with/sam-cell-seg/6 | with | 6 | pass | 2.0.50 |
| with/sam-cell-seg/7 | with | 7 | pass | 2.0.50 |
| with/sam-cell-seg/8 | with | 8 | pass | 2.0.50 |
| with/sam-cell-seg/9 | with | 9 | pass | 2.0.50 |
| with/sam-cell-seg/10 | with | 10 | pass | 2.0.50 |
| with/torch-pipeline-parallelism/1 | with | 1 | pass | 2.0.50 |
| with/torch-pipeline-parallelism/2 | with | 2 | pass | 2.0.50 |
| with/torch-pipeline-parallelism/3 | with | 3 | pass | 2.0.50 |
| with/torch-pipeline-parallelism/4 | with | 4 | pass | 2.0.50 |
| with/torch-pipeline-parallelism/5 | with | 5 | pass | 2.0.50 |
| with/torch-pipeline-parallelism/6 | with | 6 | pass | 2.0.50 |
| with/torch-pipeline-parallelism/7 | with | 7 | pass | 2.0.50 |
| with/torch-pipeline-parallelism/8 | with | 8 | pass | 2.0.50 |
| with/torch-pipeline-parallelism/9 | with | 9 | pass | 2.0.50 |
| with/torch-pipeline-parallelism/10 | with | 10 | pass | 2.0.50 |
| with/torch-tensor-parallelism/1 | with | 1 | pass | 2.0.50 |
| with/torch-tensor-parallelism/2 | with | 2 | pass | 2.0.50 |
| with/torch-tensor-parallelism/3 | with | 3 | pass | 2.0.50 |
| with/torch-tensor-parallelism/4 | with | 4 | pass | 2.0.50 |
| with/torch-tensor-parallelism/5 | with | 5 | pass | 2.0.50 |
| with/torch-tensor-parallelism/6 | with | 6 | pass | 2.0.50 |
| with/torch-tensor-parallelism/7 | with | 7 | pass | 2.0.50 |
| with/torch-tensor-parallelism/8 | with | 8 | pass | 2.0.50 |
| with/torch-tensor-parallelism/9 | with | 9 | pass | 2.0.50 |
| with/torch-tensor-parallelism/10 | with | 10 | pass | 2.0.50 |
| with/video-processing/1 | with | 1 | pass | 2.0.50 |
| with/video-processing/2 | with | 2 | pass | 2.0.50 |
| with/video-processing/3 | with | 3 | pass | 2.0.50 |
| with/video-processing/4 | with | 4 | pass | 2.0.50 |
| with/video-processing/5 | with | 5 | pass | 2.0.50 |
| with/video-processing/6 | with | 6 | pass | 2.0.50 |
| with/video-processing/7 | with | 7 | pass | 2.0.50 |
| with/video-processing/8 | with | 8 | pass | 2.0.50 |
| with/video-processing/9 | with | 9 | pass | 2.0.50 |
| with/video-processing/10 | with | 10 | pass | 2.0.50 |
| without/dna-insert/1 | without | 1 | pass | 2.0.50 |
| without/dna-insert/2 | without | 2 | pass | 2.0.50 |
| without/dna-insert/3 | without | 3 | pass | 2.0.50 |
| without/dna-insert/4 | without | 4 | pass | 2.0.50 |
| without/dna-insert/5 | without | 5 | pass | 2.0.50 |
| without/dna-insert/6 | without | 6 | pass | 2.0.50 |
| without/dna-insert/7 | without | 7 | pass | 2.0.50 |
| without/dna-insert/8 | without | 8 | pass | 2.0.50 |
| without/dna-insert/9 | without | 9 | pass | 2.0.50 |
| without/dna-insert/10 | without | 10 | pass | 2.0.50 |
| without/filter-js-from-html/1 | without | 1 | pass | 2.0.50 |
| without/filter-js-from-html/2 | without | 2 | pass | 2.0.50 |
| without/filter-js-from-html/3 | without | 3 | pass | 2.0.50 |
| without/filter-js-from-html/4 | without | 4 | pass | 2.0.50 |
| without/filter-js-from-html/5 | without | 5 | pass | 2.0.50 |
| without/filter-js-from-html/6 | without | 6 | pass | 2.0.50 |
| without/filter-js-from-html/7 | without | 7 | pass | 2.0.50 |
| without/filter-js-from-html/8 | without | 8 | pass | 2.0.50 |
| without/filter-js-from-html/9 | without | 9 | pass | 2.0.50 |
| without/filter-js-from-html/10 | without | 10 | pass | 2.0.50 |
| without/model-extraction-relu-logits/1 | without | 1 | pass | 2.0.50 |
| without/model-extraction-relu-logits/2 | without | 2 | pass | 2.0.50 |
| without/model-extraction-relu-logits/3 | without | 3 | pass | 2.0.50 |
| without/model-extraction-relu-logits/4 | without | 4 | pass | 2.0.50 |
| without/model-extraction-relu-logits/5 | without | 5 | pass | 2.0.50 |
| without/model-extraction-relu-logits/6 | without | 6 | pass | 2.0.50 |
| without/model-extraction-relu-logits/7 | without | 7 | pass | 2.0.50 |
| without/model-extraction-relu-logits/8 | without | 8 | pass | 2.0.50 |
| without/model-extraction-relu-logits/9 | without | 9 | pass | 2.0.50 |
| without/model-extraction-relu-logits/10 | without | 10 | pass | 2.0.50 |
| without/polyglot-rust-c/1 | without | 1 | pass | 2.0.50 |
| without/polyglot-rust-c/2 | without | 2 | pass | 2.0.50 |
| without/polyglot-rust-c/3 | without | 3 | pass | 2.0.50 |
| without/polyglot-rust-c/4 | without | 4 | pass | 2.0.50 |
| without/polyglot-rust-c/5 | without | 5 | pass | 2.0.50 |
| without/polyglot-rust-c/6 | without | 6 | pass | 2.0.50 |
| without/polyglot-rust-c/7 | without | 7 | pass | 2.0.50 |
| without/polyglot-rust-c/8 | without | 8 | pass | 2.0.50 |
| without/polyglot-rust-c/9 | without | 9 | pass | 2.0.50 |
| without/polyglot-rust-c/10 | without | 10 | pass | 2.0.50 |
| without/regex-chess/1 | without | 1 | pass | 2.0.50 |
| without/regex-chess/2 | without | 2 | pass | 2.0.50 |
| without/regex-chess/3 | without | 3 | pass | 2.0.50 |
| without/regex-chess/4 | without | 4 | pass | 2.0.50 |
| without/regex-chess/5 | without | 5 | pass | 2.0.50 |
| without/regex-chess/6 | without | 6 | pass | 2.0.50 |
| without/regex-chess/7 | without | 7 | pass | 2.0.50 |
| without/regex-chess/8 | without | 8 | pass | 2.0.50 |
| without/regex-chess/9 | without | 9 | pass | 2.0.50 |
| without/regex-chess/10 | without | 10 | pass | 2.0.50 |
| without/sam-cell-seg/1 | without | 1 | pass | 2.0.50 |
| without/sam-cell-seg/2 | without | 2 | pass | 2.0.50 |
| without/sam-cell-seg/3 | without | 3 | pass | 2.0.50 |
| without/sam-cell-seg/4 | without | 4 | pass | 2.0.50 |
| without/sam-cell-seg/5 | without | 5 | pass | 2.0.50 |
| without/sam-cell-seg/6 | without | 6 | pass | 2.0.50 |
| without/sam-cell-seg/7 | without | 7 | pass | 2.0.50 |
| without/sam-cell-seg/8 | without | 8 | pass | 2.0.50 |
| without/sam-cell-seg/9 | without | 9 | pass | 2.0.50 |
| without/sam-cell-seg/10 | without | 10 | pass | 2.0.50 |
| without/torch-pipeline-parallelism/1 | without | 1 | pass | 2.0.50 |
| without/torch-pipeline-parallelism/2 | without | 2 | pass | 2.0.50 |
| without/torch-pipeline-parallelism/3 | without | 3 | pass | 2.0.50 |
| without/torch-pipeline-parallelism/4 | without | 4 | pass | 2.0.50 |
| without/torch-pipeline-parallelism/5 | without | 5 | pass | 2.0.50 |
| without/torch-pipeline-parallelism/6 | without | 6 | pass | 2.0.50 |
| without/torch-pipeline-parallelism/7 | without | 7 | pass | 2.0.50 |
| without/torch-pipeline-parallelism/8 | without | 8 | pass | 2.0.50 |
| without/torch-pipeline-parallelism/9 | without | 9 | pass | 2.0.50 |
| without/torch-pipeline-parallelism/10 | without | 10 | pass | 2.0.50 |
| without/torch-tensor-parallelism/1 | without | 1 | pass | 2.0.50 |
| without/torch-tensor-parallelism/2 | without | 2 | pass | 2.0.50 |
| without/torch-tensor-parallelism/3 | without | 3 | pass | 2.0.50 |
| without/torch-tensor-parallelism/4 | without | 4 | pass | 2.0.50 |
| without/torch-tensor-parallelism/5 | without | 5 | pass | 2.0.50 |
| without/torch-tensor-parallelism/6 | without | 6 | pass | 2.0.50 |
| without/torch-tensor-parallelism/7 | without | 7 | pass | 2.0.50 |
| without/torch-tensor-parallelism/8 | without | 8 | pass | 2.0.50 |
| without/torch-tensor-parallelism/9 | without | 9 | pass | 2.0.50 |
| without/torch-tensor-parallelism/10 | without | 10 | pass | 2.0.50 |
| without/video-processing/1 | without | 1 | pass | 2.0.50 |
| without/video-processing/2 | without | 2 | pass | 2.0.50 |
| without/video-processing/3 | without | 3 | pass | 2.0.50 |
| without/video-processing/4 | without | 4 | pass | 2.0.50 |
| without/video-processing/5 | without | 5 | pass | 2.0.50 |
| without/video-processing/6 | without | 6 | pass | 2.0.50 |
| without/video-processing/7 | without | 7 | pass | 2.0.50 |
| without/video-processing/8 | without | 8 | pass | 2.0.50 |
| without/video-processing/9 | without | 9 | pass | 2.0.50 |
| without/video-processing/10 | without | 10 | pass | 2.0.50 |
