# Provenance

- Source: authored locally for OpenBench (original task, not imported).
- Trigger task: new 3-file Python project plus noise directories for the OpenCode harness A/B rerun (PRs 913 and 2367).
- Oracle: checker.sh runs `python3 -m unittest discover -s tests`. Bare `python3 -m unittest` does not load `tests/test_app.py`.
