# F01 provider-fault rescore (Researcher ruling, 2026-10-26)

The overrides come from `overrides.csv` (evidence: `results/step8-pins-D4/scored_fault_audit.md`, #154). `apply_overrides.py` builds an overlay copy of the affected PRs' cells, so the originals are never modified. It then runs the frozen step-8 metrics (`results/step8-full413-1020/stats.py`, unchanged), which reproduces SUMMARY-F01-1/2 byte-for-byte on the "before" side.

Reproduce: `python3 results/step8-full413-1020-F01/rescore-provider-faults/apply_overrides.py $PWD /tmp/s8rs/ov`. This writes `stats-before.txt` and `stats-after.txt`.

| PR | cell | change | w/o solved | with solved | token diff [95% CI] | effect call | pass-rate call |
|---|---|---|---|---|---|---|---|
| 1545 trig-lsp-ts | without t22 | wrong_answer→infra (excluded) | 29/30 → 29/29 | 30/30 | −4.3% [−16.8, +10.4] → −6.3% [−17.9, +7.6] | no effect detected → no effect detected | p=1 → p=1, no pass-rate effect |
| 579 trig-read-lines | without t27 | hang→infra (label only, `failure_class_relabel`) | 0/30 → 0/30 | 0/30 | −4.9% [−12.5, +3.3], unchanged | unchanged | unchanged |

Neither call changes.
