# Provenance

- Source: authored locally for the thesis Oh My Pi A/B stage.
- Trigger for OMP row 31 (bash.md drops the NEVER grep/ls/find and head/tail rules, about -132 tok). Also usable for rows 18 (grep limit 100->20), 29 (MUST use specialized tools), 27 (search `paths` optional) and 34 (`shell grep` wording). Locating 35 call sites across 12 files makes the model search, so the search-tool-vs-shell choice is exercised naturally.
- Fixture: `svc/api.py` defines `legacy_fetch(url, timeout=5)` and `fetch_v2(url, timeout=5)` with identical behaviour; 35 calls to `legacy_fetch(` spread over 12 modules (1 to 6 per file), some via `api.legacy_fetch(`, some imported by name. One comment mentions `legacy_fetch` in prose and one string literal contains `"legacy_fetch"` in a log message; the oracle counts only code (AST names/attributes), so those are allowed either way.
- Oracle: no AST Name/Attribute/import alias named `legacy_fetch` anywhere; `api.fetch_v2` exists; the checker's own tests import every module and check each function still returns the fetched value.
