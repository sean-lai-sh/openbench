# Provenance

- Source: authored locally for the thesis Oh My Pi A/B stage (original task, not imported).
- Trigger task (generic, unforced): used for OMP rows 16 (tools block in system prompt, per-request size), #8538 (byte-stable system prompt / cross-run cache), #13 (no "state intent before each tool call"), and the always-on size rows 19, 33, 41, 42, 44.
- Bug: `ledger/currency.py::to_cents` truncates with `int(amount * 100)`, so 19.99 becomes 1998. The failing test is two modules away (`totals.py` -> `lines.py` -> `currency.py`), so the solution path needs several read/search calls.
- Oracle: checker runs its own copy of the suite (checker_data/hidden_tests) against the workspace package, so edits to tests/ cannot make it pass. The original tests/test_totals.py must be byte-identical (sha256).
