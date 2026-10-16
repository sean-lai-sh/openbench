# Detectors: trig-omp-findext (row 14)

- **Bare extension find (primary):** `find` tool calls whose pattern is a bare `*.proto` (no `**/`, no dir). Merge build: `parsePatternPath` rewrites it to `**/*.proto` from `.`, so it is recursive. Parent build: the glob is matched as given, against the separate `path` param. Record the first find call's args (pattern, path) and result count (expected 6) per run.
- **Recovery:** after a find that returned fewer than 6, did the model retry with `**/*.proto`, fall back to bash `find`/`rg --files`, or write an incomplete list? Count retries per run.
- **Wrong-schema calls:** parent-side calls that pass `path` on the merge build (the param was removed), or merge-schema calls on the parent. Count validation errors.
- Exercised = ≥1 `find` tool call. A pure-bash run is not exercised.
