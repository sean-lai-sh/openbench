# Provenance

- Source: authored locally for OpenBench (original task, not imported).
- Author: Matthew Lam / OpenBench project.
- Oracle: checker.sh (checker-owned).
- Trigger task: enlarged copy of `misleading-error` for an unforced subagent follow-up. The settings key stays `rat`. Code reads `fee_rate` from three sites (`main.py`, `billing/report.py`, `billing/export/csv_writer.py`). The other billing modules are varied fillers. A few mention `fee_` or `rate` so one grep cannot name the real call sites.
