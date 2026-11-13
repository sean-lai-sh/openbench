# #245 gating smoke at 77644112 (2026-11-12): SMOKE ONLY, not scored, not poolable

Pi and OpenCode × Sonnet 5.5 and Opus 5.5 × regex-chess (the #251 re-smoke task) × 1 trial, all with `--matched-config`. Thinking is the **lowest accepted thinking (Sonnet `between_tools`; Opus `adaptive` with `low` effort)**. The proxy writes it on the wire for both harnesses. Total spend **$2.777** (cap ~$4).

## Setup
- **Head and VM:** `776441123884afd1d2efdc3445c295afc5d372bb` (PR #245, `cursor/matched-pair-200k-thinking-off-0811`), in a fresh worktree on thesis-h1-cpu-2. Image `h1-env:1027-strace`, Vertex `global`, `--require-model-match`.
- **Harness pins:** Pi from `~/h1/pi-src`. OpenCode `ba54cee55e18b47fb70badc84ae2cbac7c83d258` (Node 20.19.2), the same as #251. Opus cells pass `--matched-effort low`. OpenCode cells pass `--model <id>` (the MODEL_REF fix).
- **Guards:** $4.00 total and $0.55 per cell (live ledger), 1,800 s wall per cell. The call limit was 20 in batch 1 and 40 in batch 2.
- **Two batches:**
  - `raw/m245g-batch.py` ran cells 1–3. It stopped a cell with SIGTERM, so cells 1 and 2 wrote **no cell record** (no trace, context or outcome fields).
  - `raw/m245g-batch2.py` replaced it from cell 3 on. It adopted cell 3, which had already finished cleanly. It stops a cell gracefully: it kills the agent container, then waits for `cell.py` to write its record. It ran cell 4 and re-ran Sonnet as cells 5 (Pi) and 6 (OpenCode) to get records.
  - Cells 1–2 are kept as extra per-call evidence. Their ledgers and bodies are complete up to the stop.
- **Body capture** (`CAPTURE` in the batch scripts, in the cell process; no repo file changed). For every proxy request `NNNN` in `cells/*/<harness>/requests/`:
  - `received`: the exact bytes the proxy read from the client socket, captured at the proxy's own `json.loads` in `do_POST`. These are committed as `.received.json`; the raw file is `.received.bin`.
  - `edited`: the body handed to `translate_body`, after the strip, sampling, block-binding and thinking edits.
  - `upstream`: the exact bytes `translate_body` returned, which were POSTed to Vertex.
  - `meta`: route, times and sha256s.

## Gate table
| cell | stop | record | requests: proxy / trace / untraced | captures | routed (requested→upstream) | wrong-model rows | received thinking / output_config | upstream thinking / output_config | load_proof | limit.context | outcome | spend |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1-pi-claude-sonnet-5-5 | wall>1800s | no (SIGTERM) | – / – / – | 13 | claude-sonnet-5-5→claude-sonnet-5-5 | 0 | {"type":"disabled"} / None | {"type":"between_tools"} / None | n/a (Pi) | no record | – | $0.516 |
| 2-opencode-claude-sonnet-5-5 | calls>=20 | no (SIGTERM) | – / – / – | 21 | claude-sonnet-5-5→claude-sonnet-5-5 | 0 | None / None | {"type":"between_tools"} / None | pass (user_agent: UA 2.0.58 vs pin 2.0.58, pin_source=bundled_package_json) | 200000 (config) | – | $0.382 |
| 3-pi-claude-opus-5-5 | no | yes | 9 / 9 / 0 | 9 | claude-opus-5-5→claude-opus-5-5 | 0 | {"type":"disabled"} / None | {"type":"adaptive"} / {"effort":"low"} | n/a (Pi) | 200000 (live) | solved | $0.421 |
| 4-opencode-claude-opus-5-5 | cell spend>=$0.55 | yes | 5 / – / – | 5 | claude-opus-5-5→claude-opus-5-5 | 0 | None / None | {"type":"adaptive"} / {"effort":"low"} | pass (user_agent: UA 2.0.58 vs pin 2.0.58, pin_source=bundled_package_json) | 200000 (config) | solved | $0.550 |
| 5-pi-claude-sonnet-5-5 | wall>1800s | yes | 27 / – / – | 27 | claude-sonnet-5-5→claude-sonnet-5-5 | 0 | {"type":"disabled"} / None | {"type":"between_tools"} / None | n/a (Pi) | not in record (stopped by guard) | solved | $0.496 |
| 6-opencode-claude-sonnet-5-5 | no | yes | 3 / 2 / 1 | 3 | claude-sonnet-5-5→claude-sonnet-5-5 | 0 | None / None | {"type":"between_tools"} / None | pass (user_agent: UA 2.0.58 vs pin 2.0.58, pin_source=bundled_package_json) | 200000 (config) | wrong_answer | $0.411 |


- **Records:** "no (SIGTERM)" means batch 1 stopped the cell with SIGTERM, so it has no record. "–" means the record exists, but the field is null because the agent was stopped by a guard before `run_cell` finished its trace.
- **Captures vs ledger:** cell 2 has 21 captures and 20 ledger rows, because one request was in flight at the stop.
- **Routing (MODEL_REF fix):** all 77 ledger rows have requested model = upstream model = the cell model, with 0 wrong-model rows. The Opus OpenCode cell asked for and got `claude-opus-5-5` on every request, title call included (`harness_model anthropic/claude-opus-5-5`, `small_model anthropic/claude-opus-5-5`).
- **Ledger fields:** `received_thinking_json`, `received_output_config_json`, `upstream_thinking_json` and `upstream_output_config_json` are present on every row.
  - Pi sends `{"type":"disabled"}` (its matched CLI setting) and no `output_config`.
  - OpenCode sends neither field (77644112 keeps thinking out of its config).
  - The proxy writes the same upstream objects for both harnesses.
- **`load_proof` (OpenCode):** `pass`, basis `user_agent`. This comes from `raw/m245g-proof.py`, written to `analysis/opencode-proof.json`.
  - The smoke `cell.py` passes no `anthropic_sdk` pin in `OBENCH_OPENCODE_PROXY`, so `run_cell` never arms the module hook and writes no `load_proof` itself, at this head or before.
  - Instead, the pin is read from the build's bundled `packages/opencode/package.json`: `2.0.58`, `pin_source=bundled_package_json` (`sdk_pin.bundled_anthropic_pin` on the OpenCode mirror).
  - The loaded version is the `ai-sdk/anthropic/2.0.58` User-Agent suffix the proxy logged live on every OpenCode cell. The binary's compiled-in version is also `2.0.58` (`provider_embedded`). `judge_load_proof(pin, ua_version)` returns pass.
  - Cell 6's record also has `provider_loaded_source=embedded`, `provider_loaded_version=2.0.58`.
  - Pi has no `@ai-sdk/anthropic` load, so this is n/a.
- **`limit.context`:**
  - **Pi:** live `model_context_window` 200000 in cell 3's record. Cell 5 was stopped by the wall guard and its record has no context field. Cell 1 has no record.
  - **OpenCode:** 200000 (`limit.output` 128000) in the config document. It was regenerated with this head's `comparison_config(sdk, model)` and `OBENCH_MATCHED_CONFIG=1`, the same call `cell.py` makes, and contains no thinking option. The config is passed by env and not saved by the cell, so this check is offline.
- **Every request traced:**
  - Pi cell 3: 9 / 9 / 0, PASS.
  - OpenCode cell 6: 3 / 2 / 1. The one untraced request is consistent with OpenCode's title call (no tools, short system), which its trace does not count.
  - The other cells were stopped by a guard before the trace was attached.
  - The proxy ledger is the trace of record here. Every captured request has a ledger row, apart from the one in-flight request in cell 2.

## Thinking tokens (covariate): per call, per harness, within each model
Format: `thinking (cache read / cache write)`, from response `usage`, in ledger (completion) order. In OpenCode cells, ledger row 1 is the title call (no tools, about 1.5K-token prompt, 14 output tokens, 0 thinking). The first main call is ledger row 2.


**claude-sonnet-5-5**

| call | 1-pi-claude-sonnet-5-5 | 2-opencode-claude-sonnet-5-5 | 5-pi-claude-sonnet-5-5 | 6-opencode-claude-sonnet-5-5 |
|---|---|---|---|---|
| 1 | 0 (0/3199) | 0 (0/1542) | 0 (0/3199) | 0 (0/1542) |
| 2 | 121 (0/5221) | 0 (0/16178) | 0 (3199/2022) | 0 (0/16178) |
| 3 | 0 (0/5481) | 0 (0/18194) | 525 (0/5714) | 0 (0/18239) |
| 4 | 94 (0/25837) | 404 (18194/162) | 446 (5714/762) |  |
| 5 | 0 (25837/470) | 489 (0/18948) | 0 (0/7224) |  |
| 6 | 0 (26307/8408) | 557 (18948/858) | 177 (0/7588) |  |
| 7 | 229 (34715/461) | 108 (19806/1021) | 97 (5221/3297) |  |
| 8 | 92 (35176/428) | 264 (20827/514) | 100 (8518/534) |  |
| 9 | 194 (35604/512) | 340 (21341/1335) | 274 (9052/920) |  |
| 10 | 0 (36116/636) | 177 (22676/1304) | 135 (9972/1444) |  |
| 11 | 64 (36752/569) | 296 (23980/1008) | 116 (11416/1635) |  |
| 12 | 0 (0/38177) | 355 (24988/2729) | 406 (13051/284) |  |
| 13 | 97 (38177/2465) | 199 (27717/1442) | 172 (13335/1329) |  |
| 14 |  | 131 (29159/871) | 312 (14664/2242) |  |
| 15 |  | 0 (30030/780) | 371 (16906/756) |  |
| 16 |  | 0 (30810/1049) | 211 (17662/1363) |  |
| 17 |  | 0 (31859/173) | 160 (19025/612) |  |
| 18 |  | 0 (32032/361) | 298 (19637/704) |  |
| 19 |  | 270 (32393/4391) | 281 (20341/1787) |  |
| 20 |  | 372 (36784/503) | 122 (22128/3378) |  |
| 21 |  |  | 0 (25506/2511) |  |
| 22 |  |  | 230 (28017/2484) |  |
| 23 |  |  | 87 (30501/775) |  |
| 24 |  |  | 113 (31276/961) |  |
| 25 |  |  | 76 (32237/1152) |  |
| 26 |  |  | 70 (33389/452) |  |
| 27 |  |  | 317 (0/34643) |  |

| harness | cells | calls | thinking total | mean / call | median / call | calls with thinking > 0 | max |
|---|---|---|---|---|---|---|---|
| pi (1-pi-claude-sonnet-5-5) | 1 | 13 | 891 | 68.5 | 64 | 7 | 229 |
| opencode (2-opencode-claude-sonnet-5-5) | 1 | 20 | 3962 | 198.1 | 188 | 13 | 557 |
| pi (5-pi-claude-sonnet-5-5) | 1 | 27 | 5096 | 188.7 | 160 | 23 | 525 |
| opencode (6-opencode-claude-sonnet-5-5) | 1 | 3 | 0 | 0.0 | 0 | 0 | 0 |
| **pi, pooled** | 2 | 40 | 5987 | 149.7 | 114 | 30 | 525 |
| **opencode, pooled** | 2 | 23 | 3962 | 172.3 | 131 | 13 | 557 |

**claude-opus-5-5**

| call | 3-pi-claude-opus-5-5 | 4-opencode-claude-opus-5-5 |
|---|---|---|
| 1 | 6557 (0/3200) | 0 (0/1543) |
| 2 | 67 (3200/8456) | 43 (0/16175) |
| 3 | 141 (11656/3304) | 7077 (0/18104) |
| 4 | 84 (14960/3091) | 138 (16175/7026) |
| 5 | 0 (18051/3422) | 20 (0/23694) |
| 6 | 137 (21473/3325) |  |
| 7 | 112 (24798/517) |  |
| 8 | 27 (25315/501) |  |
| 9 | 0 (25816/1026) |  |

| harness | cells | calls | thinking total | mean / call | median / call | calls with thinking > 0 | max |
|---|---|---|---|---|---|---|---|
| pi (3-pi-claude-opus-5-5) | 1 | 9 | 7125 | 791.7 | 84 | 7 | 6557 |
| opencode (4-opencode-claude-opus-5-5) | 1 | 5 | 7278 | 1455.6 | 43 | 4 | 7077 |
| **pi, pooled** | 1 | 9 | 7125 | 791.7 | 84 | 7 | 6557 |
| **opencode, pooled** | 1 | 5 | 7278 | 1455.6 | 43 | 4 | 7077 |


Excluding the title calls, OpenCode means are: Sonnet cell 2, 208.5 (19 calls); Sonnet pooled, 188.7 (21 calls); Opus cell 4, 1,819.5 (4 calls).

**Pi vs OpenCode on identical upstream thinking bytes**
- **Sonnet:** no large difference. Pi pooled is 149.7 per call (median 114); OpenCode pooled is 172.3 (median 131). The spread inside each harness is larger than the gap between them: Pi cell 1 is 68.5 and cell 5 is 188.7; OpenCode cell 2 is 198.1 and cell 6 is 0.
- **Opus:** totals are about the same (7,125 vs 7,278). Each is dominated by one large call: 6,557 on Pi's first call and 7,077 on OpenCode's first main call. OpenCode's per-call mean is about 2× Pi's only because its cell was cut at $0.55 after 4 main calls.
- **Flag for review before scoring (harness, not body):** the thinking and output_config **body** bytes are identical, but the **`anthropic-beta` header sent upstream differs by harness.**
  - Pi: `mid-conversation-output-config-2026-07-01,thinking-binding-controls-2026-08-01,inline-tools-2026-09-15`.
  - OpenCode: `interleaved-thinking-2025-05-14,fine-grained-tool-streaming-2025-05-14`, after the proxy strips `claude-code-20250219`.
  - Headers come from the proxy's cache-miss header logs, which show one set per harness.
  - With n=1 per cell, this run can't tell whether the header changes thinking tokens.
- **OpenCode output cap:** OpenCode sends `max_tokens` 32000, while Pi sends 128000. Cell 6's third call hit the 32,000-token output cap with 0 thinking, and the cell ended `wrong_answer`.

## Upstream thinking / output_config bytes, cross-harness

| model | Pi upstream bytes | OpenCode upstream bytes | identical |
|---|---|---|---|
| claude-sonnet-5-5 | `"thinking": {"type": "between_tools"}`, no output_config | `"thinking": {"type": "between_tools"}`, no output_config | YES |
| claude-opus-5-5 | `"thinking": {"type": "adaptive"}`, `"output_config": {"effort": "low"}` | `"thinking": {"type": "adaptive"}`, `"output_config": {"effort": "low"}` | YES |

These are the exact substrings of the raw upstream bodies on every main call. Both harnesses carry one value per model, and it is byte-identical across Pi and OpenCode.

## Raw-byte offsets (consecutive main calls; computed on the raw `received` and `upstream` bodies)

| cell | pairs | first div at prev cc marker (received / upstream) | append-only with cc stripped (received / upstream) | exceptions |
|---|---|---|---|---|
| 1-pi-claude-sonnet-5-5 | 12 | 12 / 12 | 12 / 12 | none |
| 2-opencode-claude-sonnet-5-5 | 19 | 19 / 19 | 19 / 19 | none |
| 3-pi-claude-opus-5-5 | 8 | 8 / 8 | 8 / 8 | none |
| 4-opencode-claude-opus-5-5 | 3 | 2 / 2 | 2 / 2 | main 4: rcv div 8865 other keys: system |
| 5-pi-claude-sonnet-5-5 | 26 | 26 / 26 | 26 / 26 | none |
| 6-opencode-claude-sonnet-5-5 | 1 | 1 / 1 | 1 / 1 | none |
- **Same shape as #255:** every exception-free pair first differs at the previous call's moved last-block `cache_control` marker, in both the received and the upstream bytes. With markers removed, each pair is append-only.
- **OpenCode title calls** (no tools) sit between main calls and are excluded from the pairs.
- **The one exception, OpenCode Opus main 4 → 5 (ledger row 5):** OpenCode's own system prompt changed from `Today's date: Thu Nov 12 2026` to `Fri Nov 13 2026` when the container clock (UTC) crossed midnight. That call read 0 cache. It is a native OpenCode client-byte change, not a proxy edit.

## Cache (gate 2: matches #255 run B; reads and writes are a covariate)
**PASS.** The pattern is the same as #255 run B on both harnesses:
- Early calls often miss even when the bytes only append.
- Once a call reads, the next reads equal the previous read plus write.
- Occasional misses happen mid-run: Pi Sonnet cell 1 call 12, Pi cell 5 calls 5–6 and 27, and OpenCode Opus row 5 (the date change above).

Per-call reads and writes are in the thinking tables above.

## Spend (proxy ledger, `thesis.ab.summarize.row_cost`)
Cells 1–6: $0.516, $0.382, $0.421, $0.550, $0.496, $0.411, for **$2.777** total. That includes the two SIGTERM-stopped cells.

## Archive, scrubbing, files
- **Raw run:** the unscrubbed run stays on the VM at `~/h2/matched245-gate-1112` (nothing deleted). It is archived at `~/h2/matched245-gate-1112-raw.tgz`, sha256 `7336b18fa1ec3894d04b397f46f8cb7d12d6ec19276b0c4ae4fdbd60e37eef64` (`request-bodies-raw-archive.sha256`). `request-bodies-raw-sha256.txt` has the sha256, size and path of every raw file, including each `received.bin` and `upstream.json` the offsets were computed on.
- **`raw/`:** `obench/scrub.py` output. Before scrubbing, in the copy only:
  - `Authorization`, `x-api-key` and `host` header values in `*.cache-miss-headers.jsonl` were set to `<REMOVED>`.
  - `received.bin` was renamed to `.received.json`.
  - `scrub.py --check raw/` reports only `head.txt`, the commit sha, which was restored after scrubbing.
  - Signed thinking blocks and long blobs are redacted in the scrubbed bodies, so offsets only hold for the raw bodies.
  - Workspace tarballs are in the raw archive only and are not committed.
- **`analysis/`:**
  - `analysis.json`, from `raw/m245g-an.py` on the raw files.
  - `opencode-proof.json`, from `raw/m245g-proof.py`.
  - `m245g-readme-final.py`, the table generator for this README. It is the same as `raw/m245g-readme.py` apart from two table-label tweaks.
  - `SCRIPTS-*.sha256` hash the scripts as run on the VM and as committed. The launchers, `m245g-pack.sh` and `m245g-proof.py` differ only by `<HOME>`.
