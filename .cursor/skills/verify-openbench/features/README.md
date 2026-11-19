# Feature map

Stub proofs stay on this checkout's CLI. They do not call a model.

| Feature | File | What a stub drive runs |
| --- | --- | --- |
| `run_cell` | [run-cell.md](run-cell.md) | `python3 -m thesis.ab.run_ab … --dry-run` (plan only; `execute_cell` is not entered) |
| `step8_gate` | [step8-gate.md](step8-gate.md) | Unit tests always. `step8_gate --complete` when `results/step8-f032-1027` is present. Spend projection and the `$60` cap are sub-features. |
| Scoring | [scoring.md](scoring.md) | `step8_scoring_parity` replay of the 180 recorded cells, then `summarize` on that batch |
| Pi adapter | [pi-adapter.md](pi-adapter.md) | Pending [PR #134](https://github.com/sean-lai-sh/openbench/pull/134). On main, `obench.tests.test_pi_ab` stubs the proxy. The live `cell.sh` smoke is not a stub. |
