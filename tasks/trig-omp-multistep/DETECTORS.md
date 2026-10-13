# Detectors: trig-omp-multistep

Shared generic task; which detector applies depends on the row.

- **Row 16 (tools block), rows 19/33/41/42/44 (size rows):** per provider request, `input_tokens + cache_creation_input_tokens + cache_read_input_tokens` from the proxy meter. Report request #1 separately (system prompt delta shows there undiluted) and the per-run mean. Exercised = always; confirm by system-prompt length of request #1 (row 16 merge contains `<tools>` and `<tool name=`).
- **#8538 (byte-stable system prompt):** request #1 of each run: `cache_read_input_tokens` vs `cache_creation_input_tokens`. Merge should show cache_read ≈ system-prompt size on runs 2..N of a block; parent should show cache_creation each run (its system prompt embeds the per-run cwd). Requirements: run each side in a contiguous block, runs <5 min apart, unique cwd per run (default runner temp dirs). Exercised = consecutive same-side runs with differing cwd within TTL; report the gap between runs.
- **#13 (intent sentence):** for each assistant message containing ≥1 tool call, count whether it also contains a non-empty text block before the first tool call. Metric = fraction of tool-calling messages with leading text, plus total output tokens.

## Added in batch 2 (rows 33, 44, 19)

- **Row 33 (bash.md lists shell builtins/aux utils, about +165 tok):** per-request input-token delta (request #1 undiluted). Behaviour: bash calls using utilities named in the new list (`rg`, `fd`, `sed`, `jq`, `head`, `tail`) vs before. Keep `PI_DISABLE_UUTILS_BUILTINS` unset, otherwise the list isn't rendered (exercised = request #1 bash tool description contains `aux utils available`).
- **Row 44 (dedup system-prompt rules + xd:// ref fix, about -161 tok):** per-request input-token delta. Exercised = always; confirm request #1 system prompt no longer repeats the deduped lines (e.g. one `NEVER open guessed files` occurrence).
- **Row 19 (consolidated system prompt rewrite, about -82 tok):** input-token delta; behaviour proxies: tool calls to solve, count of distinct approaches (edits to files other than ledger/currency.py that are later reverted). Exercised = always.
