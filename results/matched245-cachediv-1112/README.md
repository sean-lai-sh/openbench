# #245 (29236b59) Pi cache-gate diagnosis, runs A + B (2026-11-12): DIAGNOSTIC ONLY, not scored

**This is a diagnostic, not a result.** Nothing here is scored or poolable. Every cell was stopped by a guard (spend or wall clock) before the task finished. Total spend **$1.674** of the $2.20 cap.

## What ran
- **VM and pins:** thesis-h1-cpu-2, head `29236b59` (#245 proxy), Pi harness, regex-chess, image `h1-env:1027-strace`, Vertex `global`. One cell per arm × model, in this order, 2026-11-12 22:11–23:08 UTC:
  1. **A, Sonnet 5.5:** matched config (`OBENCH_MATCHED_CONFIG=1`, `--matched-config`). Pi sends `--thinking off` → `thinking {type: disabled}`, and the proxy edit rewrites it to `{type: between_tools}`.
  2. **A, Opus 5.5:** same, plus `--matched-effort low`. The proxy edit rewrites Pi's `{type: disabled}` to `{type: adaptive}` + `output_config {effort: low}`.
  3. **B, Sonnet 5.5:** passthrough with Pi's normal thinking (no `--thinking off`, no matched config). Pi itself sends `thinking {type: adaptive, display: summarized, block_binding: {prefix_mismatch_behavior: drop_block}}` + `output_config {effort: low}`. The proxy edit changes nothing (`changed: false` on every call).
  4. **B, Opus 5.5:** same as 3.
- **Guards** (`raw/m245c-batch.py`): $2.20 total, $0.55 per cell, 12 calls or 900 s per cell. Cell 1 hit the $0.55 cell cap after 10 billed calls (call 11 was in flight and is not billed). Cells 2–4 hit the 900 s wall.
- **Body capture:** the launcher wraps `thesis.ab.vertex_anthropic_proxy.apply_disabled_thinking` inside the cell process. For every call it writes the body Pi sent (`NNNN.client.json`, before the proxy edit), then runs the original function, then writes the body the proxy forwards (`NNNN.forwarded.json`, after the edit), plus `NNNN.meta.json` (`changed`, model). No repo file was changed. Bodies are `json.dumps(parsed)`, the same serialisation the proxy forwards. Key order: model, messages, max_tokens, stream, system, tools, thinking, output_config.

## Per-call tables
Cache read/write, uncached input, output and thinking tokens are from the proxy ledger (`usage`). Start time is the capture file's mtime. "Pi-byte div" is the first byte at which Pi's raw body for call k differs from call k−1; the number in brackets is the byte offset, in call k−1, of the `cache_control` marker on its last message block. "fwd-byte div" is the same for the forwarded bodies. "Append-only" means that once every `cache_control` key is removed from both bodies, the first differing byte is exactly where call k−1's `messages` array closed, so call k only appends. All offsets are into the **raw** bodies (sha256 in `request-bodies-raw-sha256.txt`), not the scrubbed copies.

### 1-A-pi-claude-sonnet-5-5-regex-chess

| call | start UTC | gap s | status | cache read | cache write | uncached in | output | thinking tok | Pi-byte div (prev cc marker) | fwd-byte div | append-only (cc stripped) client/fwd | other keys changed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 22:12:00 | – | 200 | 0 | 3199 | 4 | 100 | 0 | – | – | – | – |
| 2 | 22:12:02 | 1.9 | 200 | 0 | 5221 | 2 | 27009 | 0 | 1770 (1770) | 1770 | Y/Y | none |
| 3 | 22:16:39 | 277.2 | 200 | 0 | 32241 | 2 | 2566 | 0 | 6980 (6980) | 6980 | Y/Y | none |
| 4 | 22:17:03 | 23.9 | 200 | 32241 | 2586 | 2 | 468 | 89 | 77171 (77171) | 77171 | Y/Y | none |
| 5 | 22:17:08 | 4.6 | 200 | 34827 | 556 | 2 | 1421 | 80 | 82538 (82538) | 82538 | Y/Y | none |
| 6 | 22:17:18 | 10.1 | 200 | 35383 | 1428 | 2 | 4794 | 89 | 84734 (84734) | 84734 | Y/Y | none |
| 7 | 22:17:49 | 30.5 | 200 | 36811 | 4814 | 2 | 946 | 119 | 88458 (88458) | 88458 | Y/Y | none |
| 8 | 22:17:56 | 7.8 | 200 | 41625 | 1460 | 2 | 309 | 82 | 98834 (98834) | 98834 | Y/Y | none |
| 9 | 22:18:00 | 3.7 | 200 | 43085 | 591 | 2 | 930 | 0 | 103158 (103158) | 103158 | Y/Y | none |
| 10 | 22:22:16 | 256.1 | 200 | 43676 | 47577 | 2 | 868 | 470 | 105417 (105417) | 105417 | Y/Y | none |
| 11 | 22:22:27 | 10.4 | killed in flight | – | – | – | – | – | 157813 (157813) | 157813 | Y/Y | max_tokens |

### 2-A-pi-claude-opus-5-5-regex-chess

| call | start UTC | gap s | status | cache read | cache write | uncached in | output | thinking tok | Pi-byte div (prev cc marker) | fwd-byte div | append-only (cc stripped) client/fwd | other keys changed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 22:22:36 | – | 200 | 0 | 3200 | 4 | 119 | 33 | – | – | – | – |
| 2 | 22:22:38 | 2.4 | 200 | 3200 | 1197 | 2 | 5530 | 5428 | 1768 (1768) | 1768 | Y/Y | none |
| 3 | 22:23:46 | 67.2 | 200 | 0 | 10673 | 2 | 2678 | 0 | 5847 (5847) | 5847 | Y/Y | none |
| 4 | 22:24:24 | 38.7 | 200 | 10673 | 3337 | 2 | 601 | 254 | 26060 (26060) | 26060 | Y/Y | none |
| 5 | 22:24:48 | 24.1 | 200 | 14010 | 726 | 2 | 398 | 28 | 32530 (32530) | 32530 | Y/Y | none |
| 6 | 22:24:59 | 11.1 | 200 | 14736 | 2787 | 2 | 274 | 73 | 34919 (34919) | 34919 | Y/Y | none |

### 3-B-pi-claude-sonnet-5-5-regex-chess

| call | start UTC | gap s | status | cache read | cache write | uncached in | output | thinking tok | Pi-byte div (prev cc marker) | fwd-byte div | append-only (cc stripped) client/fwd | other keys changed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 22:37:42 | – | 200 | 0 | 3200 | 4 | 100 | 14 | – | – | – | – |
| 2 | 22:37:49 | 7.6 | 200 | 0 | 4133 | 2 | 104 | 0 | 1770 (1770) | 1770 | Y/Y | none |
| 3 | 22:37:51 | 1.9 | 200 | 0 | 5260 | 2 | 20570 | 18113 | 5163 (5163) | 5163 | Y/Y | none |
| 4 | 22:41:35 | 223.4 | 200 | 0 | 26046 | 2 | 611 | 36 | 8104 (8104) | 8104 | Y/Y | none |

### 4-B-pi-claude-opus-5-5-regex-chess

| call | start UTC | gap s | status | cache read | cache write | uncached in | output | thinking tok | Pi-byte div (prev cc marker) | fwd-byte div | append-only (cc stripped) client/fwd | other keys changed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 22:52:47 | – | 200 | 0 | 3200 | 4 | 164 | 59 | – | – | – | – |
| 2 | 22:52:56 | 8.8 | 200 | 0 | 5283 | 2 | 11128 | 7915 | 1768 (1768) | 1768 | Y/Y | none |
| 3 | 22:54:50 | 113.7 | 200 | 0 | 16431 | 2 | 604 | 224 | 8057 (8057) | 8057 | Y/Y | none |
| 4 | 22:55:08 | 17.9 | 200 | 16431 | 947 | 2 | 620 | 0 | 49234 (49234) | 49234 | Y/Y | none |

Thinking tokens in A: Sonnet with `between_tools` still returned thinking tokens on 6 of 10 billed calls (80–470), and the forwarded history carries signed `thinking` blocks from call 5 on. Opus `adaptive`/`low` returned up to 5,428.

## Divergence: where it first appears
- **Every call, both models, both runs:** Pi's raw body first differs from the previous call at exactly the byte where the previous call's last-block `cache_control: {type: ephemeral}` marker sat. Pi moves its rolling message breakpoint to the new last user block each call. Nothing before that byte changed.
- **Before vs after the proxy edit:** the client and forwarded divergence offsets are identical on all 21 call pairs. The proxy edit only touches the top-level `thinking` (Sonnet) or `thinking` + `output_config` (Opus) keys. They sit after `tools` in the body (first edited byte 8,318–168,381, always past the `tools[3]` breakpoint), and the edit is the same on every call. No `messages`, `system` or `tools` byte is ever changed by the edit.
- **With `cache_control` keys removed:** every call is strictly append-only on both sides, and no top-level key other than `messages` changes from call to call. The one exception is A Sonnet call 11 (killed in flight, not billed), where Pi lowered `max_tokens` from 128000 to 103681.
- **The `tools[3]` and `system[0]` breakpoints** are byte-identical in every call of a cell.
- **B's message blocks:** no earlier block changes. Prior `thinking` blocks are resent unchanged with their signatures. B bodies also carry a mid-conversation `{"role": "system", "content": [], "output_config": {"effort": "medium"}}` message after the first user message on every call. Pi adds it in B, not in A, and it never moves.

## Verdict
- **Sonnet 5.5:** the divergence is already in Pi's client bytes and is identical after the edit. It is **not a proxy artifact**. By the brief's rule this is native Pi: gate 2 becomes "matches B pattern", with cache as a covariate.
- **Opus 5.5:** same. The divergence is in Pi's client bytes, identical after the edit, so it is **not a proxy artifact**. Native Pi; same gate-2 rule.
- **B (Pi's normal thinking):** B did **not** read cache from call 2 on either model. Sonnet read 0 on calls 2–4; Opus read 0 on calls 2–3 and first read on call 4 (16,431, exactly call 3's write). So the thinking setting is not what shifts the history, and no blocks change.
- **What the misses are not:** the only byte that moves is the breakpoint marker itself, and the content is append-only. On the missed calls even the unchanged `tools` + `system` prefix (identical bytes, same breakpoints) read 0. So the bytes don't explain the misses. A and B show the same shape: early calls miss, and once a call reads, later calls read exactly the previous read + write (A Sonnet calls 4–10, A Opus 4–6). A Opus call 2 read call 1's 3,200, then call 3 missed again. One upstream header set (same `anthropic-beta`, endpoint `global`) covers every missed call. This is consistent with a server-side miss (for example, `global` routing), but this run cannot prove that.

## Spend (proxy ledger, `thesis.ab.summarize.row_cost`)
| cell | calls billed | spend |
|---|---|---|
| A Sonnet | 10 | $0.670 |
| A Opus | 6 | $0.310 |
| B Sonnet | 4 | $0.311 |
| B Opus | 4 | $0.383 |
| **total** | 24 | **$1.674** (cap $2.20) |

## Archive and scrubbing
- **Raw bodies:** the unscrubbed run, including raw bodies and the unredacted header logs, stays on the VM at `~/h2/matched245-cachediv-1112`. Nothing was deleted. It is archived at `~/h2/matched245-cachediv-1112-raw.tgz`, sha256 `4ec5942363dc82501d7a5f0f19eb4d845e0dd649ad4d0c0ed5cf7a7820dcbea6` (`request-bodies-raw-archive.sha256`).
- **`request-bodies-raw-sha256.txt`:** sha256, size and path of every raw file, including each `NNNN.client.json` and `NNNN.forwarded.json` that the offsets were computed on.
- **`raw/`:** `obench/scrub.py` output of the whole run dir. Before scrubbing, the `Authorization`, `x-api-key` and `host` values in `*.cache-miss-headers.jsonl` were replaced with `<REMOVED>`, in the copy only. `scrub.py --check raw/` is clean. Signed thinking blocks and other long blobs are redacted in the scrubbed bodies, so byte offsets only hold for the raw bodies. `raw/head.txt` was restored to the commit sha after scrubbing.
- **`analysis/`:** `per-call.json`/`per-call.md` (from `raw/m245c-tab.py`) and `divergence.json` (from `raw/m245c-div.py`), computed on the raw bodies on the VM. These are scrubbed copies, so the sha256 fields inside them are redacted; use `request-bodies-raw-sha256.txt`. `SCRIPTS-as-run.sha256` and `SCRIPTS-committed.sha256` hash the scripts. The scrubbed copies are byte-identical except `m245c-launch.sh` (home path → `<HOME>`).
- `raw/m245c-x.py` prints the bytes around each divergence and the client-vs-forwarded key diff.

Related: `results/matched245-passthrough-1112` (#252, the passthrough smoke with `--thinking off`, which 400s on call 1) and `results/matched245-resmoke-1112` (#251).
