# Provenance

- Source: authored locally for OpenBench (original task, not imported).
- Trigger task: one-file workspace for the OpenCode harness A/B rerun (PR 3418).
- Both functions contain the identical lines `retries = 3` and `backoff = 2`, so an edit whose oldString is exactly `retries = 3` hits the multiple-matches error.
- Oracle: checker.sh reads the two `retries` assignments. `fetch_remote` must be 5 and `fetch_local` must stay 3.
