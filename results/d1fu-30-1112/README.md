# D1 Sonnet prompt follow-up, 30 per side, at 04521ae5 (2026-11-12)

This is the full 30-per-side run that the Researcher cleared after the #253 re-smoke. Request bodies were saved for every call on both arms. **The bodies were captured by a wrapper script (`capture/capture_run_ab.py`), not by the proxy.** The proxy at 04521ae5 only saves Codex `/v1/responses` bodies.

## Setup
- **Runner:** `04521ae557a04fc3de5256dd1ed40b46ff1c4817`, worktree `~/ob-s248` on thesis-h1-cpu-3, clean tree.
- **Environment:** thesis-h1-cpu-3, image `h2-env:1022@sha256:72c59033194aae26f6de67c62c77d742aef1d71849000e308f3ee875ff5169ff`, Vertex global, host network, `OBENCH_ADC_METADATA=1`.
- **Pair:** OpenCode PR 725226.
  - Without: `c436fc69eb039523795555f0ec88d32f20ea3292`, binary sha256 `38f987cb…`.
  - With: `d7af1f17056dd4c216b9aa62f03491c6f8fbeeb0`, binary sha256 `162ecbcd…`.
  - Both binaries are the prebuilt `build.ts --single` ones, the same as in #243 and #253.
- **Task:** trig-tmpdir, `permissions=workspace`. 30 trials per side (60 cells), `--order interleave-seeded --seed 1016`, jobs 2, `--max-cost-usd 25`, timeout 2400 s.
- **Flags:** `--model claude-sonnet-5-5 --vertex-model claude-sonnet-5-5`. The run_ab arguments are exactly the #253 smoke's except trials (30) and the cap ($25). See `capture/cell.sh`.
- **Times (ET):**
  - Launch: 17:24:38 EST, container `d1fu-30`, tmux `d1fu-30`.
  - First cell started 17:24:57 EST; last cell ended 17:32:30 EST.
  - Container exited 0 at 17:32:31 EST.

## Gates
| gate | without | with |
|---|---|---|
| `load_proof` pass (built-in 3.0.71 = pin, `pin_source=bundled_package_json`) | 30/30 | 30/30 |
| written config `limit.context` 200000 (`config-check.txt`) | yes | yes |
| every ledger request `status 200`, upstream `claude-sonnet-5-5`, `thinking_sent none` | 94/94 | 108/108 |
| row `proxy_requests` = ledger calls = `requests_count` | 30/30 | 30/30 |
| captured bodies = ledger calls, per cell | 30/30 | 30/30 |
| upstream errors / SSE errors / faults served | 0 / 0 / 0 | 0 / 0 / 0 |

- `raw/gate-check.py` (the smoke's 1-row-per-arm extractor, reused unchanged) exits 1 on this run, with "traced 0 != requests". That is a script limit, not a gate failure. It pairs ledgers to rows by `run_id`, which only works when each arm has a single ledger, so all 60 ledgers end up under `unpaired_ledgers`. The table above checks each cell's row against its ledger. Cells were matched to ledgers by exact proxy token totals, and every cell matched exactly one ledger.
- Two without cells (trials 4 and 11, both solved) have `untraced_requests=1`. The OpenCode trace recorded one request fewer than the proxy did. The proxy ledger and the body capture both have every call.
- `run.log` repeats the smoke's `cell missing required fields ['loaded_anthropic', 'cell_image']` note.
- Thinking still comes back from the server even though none is requested: 4020 thinking tokens across the run. That is the same pattern as #243 and #253.

## Results
| arm | solved | wrong_answer | other | calls (mean per cell) | spend | mean $/cell | mean wall s |
|---|---|---|---|---|---|---|---|
| without (`c436fc69`) | **22/30** | 8 | 0 | 94 (3.13) | $3.0583 | $0.1019 | 12.0 |
| with (`d7af1f17`) | **24/30** | 6 | 0 | 108 (3.60) | $3.4403 | $0.1147 | 12.9 |

- **Total spend: $6.4986**, well under the $25 cap, with no unexpected spend.
- Every wrong_answer cell has `permission_rejections` > 0, and no solved cell has any. `tmpdir_leaked_dirs` is empty on every cell.
- Per-cell rows are in `raw/725226/{without,with}.jsonl`. `analysis/cells-timeline.csv` has one line per cell with arm, trial, start and end times, the outcome, and cache fields.

## Cache
Prices: Claude Sonnet 5.5, Standard global list, `thesis/ab/vertex_list_prices.json` (read 2026-10-29). USD per million tokens: uncached input 2.00, output 10.00, 5-minute cache write 2.50, cache read 0.10. All writes are `ephemeral_5m`.

| arm | cache read (call 1, cross-cell) | cache read (call 2+, within-cell) | calls 2+ that read | cache write | cache read $ | cache write $ | cache $ |
|---|---|---|---|---|---|---|---|
| without | 0 (0/30 cells) | 309,515 | 20/64 (31%) | 1,154,471 | $0.0310 | $2.8862 | **$2.9171** |
| with | 0 (0/30 cells) | 385,681 | 25/78 (32%) | 1,296,166 | $0.0386 | $3.2404 | **$3.2790** |

- **Cache $ gap (with − without): +$0.3619.** That covers both the within-cell-only view and the total including cross-cell reads, because there were no cross-cell reads on either arm, so the two views give the same numbers.
  - The within-cell-only view reprices any call-1 read as the write it would otherwise have been; with no call-1 reads, nothing gets repriced.
  - The total-spend gap is +$0.3820, and it comes from the with arm making more calls (108 vs 94), not from a different cache pattern.
- **The smoke's "with never reads cache" did not hold.** In #253 the with cell read 0 tokens on its 3 calls. Here the with arm read cache on 25 of 78 later calls, at the same rate as without (32% vs 31%). The smoke cell was too short to show reads, because reads only appear a few seconds after the write (see below). The per-arm cost footnote should not say that the with arm never reads cache.
- **No call-1 reads on either arm, so there is no call-1 read size to compare to the system+tools prefix.**
  - Every cell's tools+system prefix is unique, on both arms. The system prompt's `Working directory:` and the bash tool description both contain the cell's own `/tmp/obench-cell-<random>/` path. That gives 30 distinct tools+system hashes per arm, and none are shared across arms.
  - A cross-cell hit at the system breakpoint is therefore impossible by construction, on both arms equally. For each call 1, `analysis/cells-timeline.csv` lists the cell that started just before it and the cells running at the same time (jobs 2, which in practice means alternating arms). It also lists any earlier same-prefix call within 5 minutes, and the list is empty for every cell.

## Prefix offsets (computed on the raw captured bodies)
Method: `capture/analyze_bodies.py` runs over the raw `forwarded` bytes on the VM. The outputs are `analysis/offsets-per-call.jsonl` (one line per call), `analysis/offsets-summary.json` and `analysis/cells-timeline.csv`.

**Verdict: d7af1f17's prompt does not change the prefix from call to call.**

- **Same prefix on every call.** Within each cell, tools+system are byte-identical on every call, on both arms: with 78/78 later calls, without 64/64.
- **Append-only history.** In Anthropic cache order (tools → system → message content blocks, with `cache_control` markers ignored), every call's previous body is an exact prefix of the next one. The first divergent block is "none" on all 142 later calls.
- **Raw byte offsets.** The first raw-byte divergence from the previous call is at 9,551 bytes or later; the minimum is 9,551 on both arms, about 21% of the body. The body's JSON key order is `max_tokens, system, messages, tools`, so this offset falls just past the system block. There, the `cache_control` marker on the newest user message moves to the next turn, which is the normal append point.
- **Why some later calls still miss.** Calls 2–4 usually come 1–3 s apart and re-write the whole prompt (about 15.3–16K tokens) instead of reading it.
  - When a read does land, its size often equals an earlier call's total input rather than the immediately previous call's: 13 of 25 reads on with and 11 of 20 on without.
  - The youngest write that was read was 1–2 s old.
  - This looks like cache-write visibility lag at the Vertex global endpoint rather than any change in the request bytes. Timestamps have 1 s resolution, so this is an observation, not proof. The pattern is the same on both arms.
- **Proxy edits.** No proxy edit was seen: on every call the client body equals the bytes passed to `translate_body` (`client_bytes_equal_pre_translate` is true). The only translation step is the standard `model` → `anthropic_version` swap.

## Body capture
- `capture/capture_run_ab.py` runs `thesis.ab.run_ab` in-process. It wraps three proxy-module functions (`split_cell_path`, `classify_call_role`, `translate_body`), calls the originals unchanged, and writes what they saw. This is the same idea as the #245 cache-divergence runs (A+B, 29236b59, `m245c-batch.py`). No repo file is edited, and a capture failure is only logged (no `errors.log` was produced).
- Files per call, under `request-bodies/<cell>/` on the VM:
  - `NNNN.pre_translate.bin`: the exact bytes the client sent (no proxy edit occurred).
  - `NNNN.forwarded.bin`: the exact upstream bytes.
  - `meta.jsonl`: sha256 and size of each file.
  - `NNNN.client.json`: only written when a proxy edit changes the body; there are none.
- **Offline identical-bytes check:** `capture/test_capture.py` and `capture/test_capture.out`, run in the same image at 04521ae5. A dummy upstream receives the same request through the unwrapped proxy and the wrapped proxy. The upstream bytes and the response are identical, the captured files equal the sent and forwarded bytes, and the check exits 0.
- **Script hashes:** `capture/SHA256SUMS` has the sha256 of each script as run on the VM, and of the committed copies. The committed `launch-d1fu30.sh` and `pack_d1fu30.py` have identity literals replaced by `<HOME>`/`<HOST>`/`<USER>`. The others are byte-identical.

## Files
- **`raw/`:** the run directory minus the bodies. It has the launcher, `cell.sh`, the capture wrapper, dry-run, run log, driver log, config-check and gate-check scripts and outputs, `prs.csv`, `task-map.csv`, per-arm jsonl / toolchain / cell json, proxy ledgers (jsonl, totals, bytes, cache-miss headers), transcripts, and workspace tarballs.
- **`request-bodies-scrubbed/`:** scrubbed copies of all 404 captured bodies, as `.json`, plus `meta.jsonl` per cell.
- **`request-bodies-raw-sha256.txt`:** sha256 and size of every raw captured file.
- **`request-bodies-raw-archive.sha256`:** sha256 of the raw archive.
- **`analysis/`:** offsets and the timeline.

**Raw bodies (off-repo, thesis-h1-cpu-3):**
- `~/h2/d1fu-30-1112/request-bodies/`.
- Archive `~/h2/d1fu-30-1112-raw-bodies.tgz`, sha256 `9e1861c6ed286e884d73f0364b768b5c92bf50bddeb9106b739030a86bc2915a`.
- The original unscrubbed run stays at `~/h2/d1fu-30-1112`. Nothing was deleted.

**Scrubbing:**
- **Bodies:** scrubbed with `obench/scrub.py` `scrub_text`. `scrub.py --check` on `request-bodies-scrubbed/` is clean for every body file. The only hits are the sha256 digests in `meta.jsonl` and the runner commit in `CAPTURE.txt` (`[hex-blob]`/`[base64-blob]`). No auth headers were ever captured, because only bodies are written.
- **Transcripts:** text files are `scrub.py` output. The tree-wide `--check` reports only `[base64-blob]` hits in the OpenCode session `opencode-default.db-wal` files (signed thinking blocks), the same class of hit as in #243 and #253. The WAL, `.db` and `.db-shm` files are left as original binaries.
- **Other text files:** `/home/box` became `<HOME>` and the VM hostname became `<HOST>`; commit ids and digests are kept.
- **Workspace tarballs:** repacked with numeric owner 0/0, so their sha256 no longer matches `final_workspace_tar_sha256` in the rows.
- A tree-wide `--check` on this directory finds no email, key, home-path, username or hostname hits; only `[hex-blob]`/`[base64-blob]` hits from digests and the WAL files.
- **No file is over 50 MB**, so there is no MANIFEST.
