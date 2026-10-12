# Detectors: trig-omp-multistep

Shared generic task; which detector applies depends on the row.

- **Row 16 (tools block), rows 19/33/41/42/44 (size rows):** per provider request, `input_tokens + cache_creation_input_tokens + cache_read_input_tokens` from the proxy meter. Report request #1 separately (system prompt delta shows there undiluted) and the per-run mean. Exercised = always; confirm by system-prompt length of request #1 (row 16 merge contains `<tools>` and `<tool name=`).
- **#8538 (byte-stable system prompt):** request #1 of each run: `cache_read_input_tokens` vs `cache_creation_input_tokens`. Merge should show cache_read ≈ system-prompt size on runs 2..N of a block; parent should show cache_creation each run (its system prompt embeds the per-run cwd). Requirements: run each side in a contiguous block, runs <5 min apart, unique cwd per run (default runner temp dirs). Exercised = consecutive same-side runs with differing cwd within TTL; report the gap between runs.
- **#13 (intent sentence):** for each assistant message containing ≥1 tool call, count whether it also contains a non-empty text block before the first tool call. Metric = fraction of tool-calling messages with leading text, plus total output tokens.
