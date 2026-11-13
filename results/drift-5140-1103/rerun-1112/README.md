# Opus 5140 drift rerun resumed 2026-11-12 (rerun-1112)

Stored beside the earlier 2026-11-03 partial data in results/drift-5140-1103/ (not overwritten).
180/180 cells (with/without, 90 each), opencode 2.0.50 pin, code head b1cbded32a92, STOPAT $300 (never reached), driver exit 0.
Transcripts scrubbed with obench/scrub.py (--check clean). Workspace tarballs (180 *.workspace.tar.gz) are NOT committed: see MANIFEST.txt (size + sha256); originals remain on VM thesis-h1-cpu under ~/h2/drift-5140-1103/opus.

## Results (raw and infra-excluded)

Recomputed from `opus/5140/with.jsonl` and `opus/5140/without.jsonl` (stored `score==1` numerators; stored `failure_class` for the infra cut). No discrepancy with the review figures.

| Cut | with | without | two-sided Fisher p |
|---|---|---|---|
| Raw | 39/90 | 44/90 | 0.5499 (≈.55) |
| Infra-excluded (drop stored `failure_class=infra`) | 39/78 | 44/82 | 0.7517 (≈.75) |

All 20 infra cells are unsolved, so the numerators do not change when they are dropped. The 9 partial 11/3 cells under `results/drift-5140-1103/` (parent of this `rerun-1112/` tree) are **not pooled**.

## Infra cells (20): cause breakdown

Stored `failure_class=infra`: 12 with, 8 without. Counts below use that stored label. `env_failure` is false on all 20.

### Agent-side API errors — 17 cells (9 with, 8 without)

All are `dna-insert`. Each cell JSON has `ledger_statuses: [400]` and `failure_reason` / `provider_error` equal to an Anthropic `invalid_request_error`:

> `Invalid signature in thinking block. The block is bound to a different conversation.`

16 cells fail at `messages.1.content.2`; `without/dna-insert/6` fails at `messages.1.content.4`. Wall time is 13–24s; the checker then reports `missing primers.fasta`. This is an agent/harness request-construction failure (replayed thinking signature), not an environment failure.

Citations are the per-cell JSON (one line each); the same objects are in the side jsonl.

| Cell | Arm | Trial | Cause | Citation |
|---|---|---|---|---|
| with/dna-insert/2 | with | 2 | `invalid_request_error` (thinking signature) | `opus/5140/cells/with/dna-insert/2.json` fields `failure_reason`, `provider_error`, `ledger_statuses=[400]` (messages.1.content.2) |
| with/dna-insert/3 | with | 3 | `invalid_request_error` (thinking signature) | `opus/5140/cells/with/dna-insert/3.json` fields `failure_reason`, `provider_error`, `ledger_statuses=[400]` (messages.1.content.2) |
| with/dna-insert/4 | with | 4 | `invalid_request_error` (thinking signature) | `opus/5140/cells/with/dna-insert/4.json` fields `failure_reason`, `provider_error`, `ledger_statuses=[400]` (messages.1.content.2) |
| with/dna-insert/5 | with | 5 | `invalid_request_error` (thinking signature) | `opus/5140/cells/with/dna-insert/5.json` fields `failure_reason`, `provider_error`, `ledger_statuses=[400]` (messages.1.content.2) |
| with/dna-insert/6 | with | 6 | `invalid_request_error` (thinking signature) | `opus/5140/cells/with/dna-insert/6.json` fields `failure_reason`, `provider_error`, `ledger_statuses=[400]` (messages.1.content.2) |
| with/dna-insert/7 | with | 7 | `invalid_request_error` (thinking signature) | `opus/5140/cells/with/dna-insert/7.json` fields `failure_reason`, `provider_error`, `ledger_statuses=[400]` (messages.1.content.2) |
| with/dna-insert/8 | with | 8 | `invalid_request_error` (thinking signature) | `opus/5140/cells/with/dna-insert/8.json` fields `failure_reason`, `provider_error`, `ledger_statuses=[400]` (messages.1.content.2) |
| with/dna-insert/9 | with | 9 | `invalid_request_error` (thinking signature) | `opus/5140/cells/with/dna-insert/9.json` fields `failure_reason`, `provider_error`, `ledger_statuses=[400]` (messages.1.content.2) |
| with/dna-insert/10 | with | 10 | `invalid_request_error` (thinking signature) | `opus/5140/cells/with/dna-insert/10.json` fields `failure_reason`, `provider_error`, `ledger_statuses=[400]` (messages.1.content.2) |
| without/dna-insert/2 | without | 2 | `invalid_request_error` (thinking signature) | `opus/5140/cells/without/dna-insert/2.json` fields `failure_reason`, `provider_error`, `ledger_statuses=[400]` (messages.1.content.2) |
| without/dna-insert/3 | without | 3 | `invalid_request_error` (thinking signature) | `opus/5140/cells/without/dna-insert/3.json` fields `failure_reason`, `provider_error`, `ledger_statuses=[400]` (messages.1.content.2) |
| without/dna-insert/4 | without | 4 | `invalid_request_error` (thinking signature) | `opus/5140/cells/without/dna-insert/4.json` fields `failure_reason`, `provider_error`, `ledger_statuses=[400]` (messages.1.content.2) |
| without/dna-insert/5 | without | 5 | `invalid_request_error` (thinking signature) | `opus/5140/cells/without/dna-insert/5.json` fields `failure_reason`, `provider_error`, `ledger_statuses=[400]` (messages.1.content.2) |
| without/dna-insert/6 | without | 6 | `invalid_request_error` (thinking signature) | `opus/5140/cells/without/dna-insert/6.json` fields `failure_reason`, `provider_error`, `ledger_statuses=[400]` (messages.1.content.4) |
| without/dna-insert/7 | without | 7 | `invalid_request_error` (thinking signature) | `opus/5140/cells/without/dna-insert/7.json` fields `failure_reason`, `provider_error`, `ledger_statuses=[400]` (messages.1.content.2) |
| without/dna-insert/9 | without | 9 | `invalid_request_error` (thinking signature) | `opus/5140/cells/without/dna-insert/9.json` fields `failure_reason`, `provider_error`, `ledger_statuses=[400]` (messages.1.content.2) |
| without/dna-insert/10 | without | 10 | `invalid_request_error` (thinking signature) | `opus/5140/cells/without/dna-insert/10.json` fields `failure_reason`, `provider_error`, `ledger_statuses=[400]` (messages.1.content.2) |

### Stored infra, wall-time timeout — 3 cells (with only); not environment

`with/sam-cell-seg` trials 1, 3, and 4. Each cell JSON has `error: timeout after 2400s`, no `failure_reason`, no `provider_error`, and no ledger 400. `agent-output.txt` has no `invalid_request_error` and no container/network/image/disk/ENOENT failure that ends the cell. The agent did real work (12–22 proxy requests, 13k–22k output tokens), then went idle (server heartbeat lines only) until the 2400s cap; the checker ran afterward and failed a unit test. The same shape is stored as `timeout` (not infra) for `with/sam-cell-seg/7`. These three are **not** treated as environment-caused. Timestamps in `agent-output.txt` are UTC; times below are America/New_York (ET, UTC-5).

| Cell | Arm | Trial | Cause | Citation |
|---|---|---|---|---|
| with/sam-cell-seg/1 | with | 1 | stored infra; committed logs show wall-time timeout after idle | `opus/5140/cells/with/sam-cell-seg/1.json` cell JSON `error: timeout after 2400s`; `transcripts/with/sam-cell-seg/1/agent-output.txt` last model work L593 at 15:24:57 ET, then heartbeat-only through L633 at 15:50:00 ET (start 15:11:29 ET) |
| with/sam-cell-seg/3 | with | 3 | stored infra; committed logs show wall-time timeout after idle | `opus/5140/cells/with/sam-cell-seg/3.json` cell JSON `error: timeout after 2400s`; `transcripts/with/sam-cell-seg/3/agent-output.txt` last model work L651 at 16:50:01 ET, then heartbeat-only until 17:25:14 ET (start 16:45:44 ET) |
| with/sam-cell-seg/4 | with | 4 | stored infra; committed logs show wall-time timeout after idle | `opus/5140/cells/with/sam-cell-seg/4.json` cell JSON `error: timeout after 2400s`; `transcripts/with/sam-cell-seg/4/agent-output.txt` last model work L309 at 17:38:58 ET, then heartbeat-only until 18:13:34 ET (start 17:36:03 ET) |

### Environment-caused infra — 0 cells

No cell in this 20 has `env_failure=true` or an environment marker (container, network, image, disk, ENOENT) as the cause. The recorded `cell_image` on every cell already is the pinned `h2-env:1022` image (digest redacted in the committed files). This result is **not** marked provisional pending a pinned-image rerun of environment cells.

## Per-cell load_proof and loaded pin

Read from the committed per-cell rows in `opus/5140/with.jsonl` and `opus/5140/without.jsonl` (same fields as `opus/5140/cells/{arm}/{task}/{trial}.json`). **All 180 cells have `load_proof=pass`.** None is missing `load_proof`. The loaded pin/version is `2.0.50` on every cell (`loaded_anthropic`, also `anthropic_pin` and `provider_loaded_version`; `load_proof_basis=user_agent`, `load_proof_reason=User-Agent 2.0.50`, `provider_version_proven=true`). The recorded `cell_image` is `h2-env:1022@sha256:<REDACTED_HEX>` on every cell; the digest was redacted by `obench/scrub.py` and is not reconstructed here.

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
