# Hermes arm (PR #240) live smoke, 2026-11-12

Not a scored run. One `polyglot-rust-c` cell per model through
`data/hermes-harness-smoke/cell.py`, exactly as committed at the PR head.

| Item | Value |
|---|---|
| PR | [#240](https://github.com/sean-lai-sh/openbench/pull/240) |
| Head run | `e8dbf49896267d368ff592d83a7419338adfd085` (the PR head at run time; unchanged since 2026-11-09) |
| Hermes pin | NousResearch/hermes-agent `4dcef215cfe41bd2d02c2d1dad6e257a18101216` (MIT), installed fresh by `prep.sh` (PREP_EXIT=0, extras `all, anthropic`) |
| Host | thesis-h1-cpu-2 (both cells, sequential) |
| Image | `h1-env:1027-strace` (`sha256:2506cd378b60…`), docker, bridge, egress sinkhole confirmed |
| Endpoint | Vertex `global`, `--require-model-match` on, ADC via VM metadata |
| Thinking | field **unset** (as committed). `between_tools` / `disabled` not sent |
| Context | 200000 (AD1-hermes-ctx); interleaved-thinking beta stripped |
| Run window | 2026-11-12 20:14:27Z – 20:16:48Z |

## Results

| | Sonnet 5.5 | Opus 5.5 |
|---|---|---|
| cell_id | `eadfe5f0ecd09336` | `24cd2b9945af5783` |
| calls (main + title) | 3 (2 + 1) | 3 (2 + 1) |
| server thinking tokens per call | **[1710, 0, 0]** (total 1710) | **[2738, 246, 0]** (total 2984) |
| cache_read per main call | [0, 0] (call 2 wrote 17843, read 0) | [0, 0] (call 2 wrote 17956, read 0) |
| tokens in / out / cache_w / cache_r | 734 / 2565 / 35001 / 0 | 734 / 4193 / 35110 / 0 |
| proxy cost (list) | $0.1146 | $0.2623 |
| outcome | completed, wrong_answer (checker exit 1) | completed, wrong_answer (checker exit 1) |
| gateway_stop | stop 0, no survivors | stop 0, no survivors |
| off_protocol | false | false |

Four checks (both models identical):

| Check | Pass |
|---|---|
| 1_traced (3/3 proxied = traced) | **pass** |
| 2_cache_read (main call 2 reads cache) | **FAIL** (call-2 miss; no later call, so region-split signature cannot be checked) |
| 3_thinking_sent (every call none **and** 0 server thinking tokens) | **FAIL** (Sonnet call 1; Opus calls 1–2) |
| 4_prompt_bytes (≤5% system/tools delta) | **pass** (0.0 delta) |

Total smoke spend: **$0.38**.

Both agents finished in one `terminal` tool call (write + compile + test) and
a final answer, so each cell has only 2 main calls.

## Reference context

The VM worktree is sparse (no `results/`), so the cell's own reference fields
came back empty. `hermes240-evidence-with-reference.json` recomputes the
evidence on the box against the #196 ledgers at the same head: pass/fail is
unchanged. Sonnet reference: OpenCode call-2 miss 28/90 cells.

`pvo196-server-thinking-tally.json`: in the #196 batch (e507e38c, Sonnet),
OpenCode sent `thinking_sent=none` on all 761 calls, but 445 of them returned
server thinking tokens (670,847 total). Pi (adaptive) returned thinking on
218/370 calls (291,901 total). So OpenCode's row-level `tokens_reasoning=0`
does not mean zero server thinking.

## Files

`raw/` holds every log, ledger, totals, cache-miss header dump, raw request
body and transcript text, scrubbed with `obench/scrub.py` (home path, user,
host, ≥32-hex blobs redacted); `scrub.py --check` on this folder is clean.
Pin and head SHAs above are the unredacted values.

Not committed (binary, not scrubbable), kept on the box and on the VM:

| File | sha256 |
|---|---|
| sonnet `hermes_polyglot-rust-c_claude-sonnet-5-5_trial1.workspace.tar.gz` | `2e7009fb326a45bd685d5cdfc0b7a7997789bd78ed9721dab338ba8af67ba9ce` |
| opus `hermes_polyglot-rust-c_claude-opus-5-5_trial1.workspace.tar.gz` | `61bf31f60f98ddede1787c2a6f43c9ab3e8b8d766592d73798937b39ff0f9297` |
| full unscrubbed archive `hermes240-smoke-1112.tgz` | `9df0df5a04785e092d25ee84dbbfad2c7457f374acfb02bc56cdfa468f448d1e` |

Originals: VM `thesis-h1-cpu-2:~/h2/hermes240-smoke-1112/`; box
`/workspace/thesis-dev/smoke-1112/`.
