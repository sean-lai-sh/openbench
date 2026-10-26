# Step 8 amendment: machine move to thesis-h1-cpu (2026-10-25, before any VM step-8 data)

Applies to: OpenCode full run, step 8 (Sonnet 5.5, 30 per side, 413-PR scope / 351 runnable, 16 batches), as described in `token-efficiency-original-study-2026-10-24.md` §"Full 413-PR Sonnet run (step 8)". Format follows the dated amendments in `hard-suite-prereg-v2.md` (A1, A2) and `harness-comparison-prereg.md` (A1, A2). No separate step-8 pre-registration file was found in `briefs/` or in `sean-lai-sh/openbench` (main d687245c6c); this amendment attaches to the study brief above.

## Amendment M1, 2026-10-25 (made before any step-8 cell has run on the VM)
- **What changed:** 56 PRs are fully scored at 30/side, all run on the shared bot computer (9-PR pilot #107, batches F01, F02, part of F03). A disk-space guard repeatedly stopped the runner there. The remaining PRs, batch F03 (remainder) through F16 (about 295 PRs), move to the GCP VM `thesis-h1-cpu`. PRs #950 and #3185 (partly run, unscored) are rerun in full on the VM.
- **What was seen at the time:** the 56 scored PRs show no pass-rate effects and four modest token effects (#795, #1109, #1443, #2051). The move is driven by disk only, not by any result.
- **Unchanged:** PR list, batches, tasks, pins, 30 per side, interleaved-seeded order and seed, scorer, token counting, effect rule and analysis.
- **A/A check before pooling:** before any VM result is pooled, stock OpenCode vs itself runs on the VM, Sonnet 5.5, 30 per side (estimated about $10). Pooling with the shared-computer cells is allowed only if the VM A/A 95% CI overlaps the existing Sonnet OpenCode A/A band of +0.1% [−6.5%, +6.8%]. If it does not, VM results are analysed and reported separately, with machine recorded, and the existing band is not used for them.
- **Machine column:** every step-8 cell (both machines, back-filled for the 56 scored PRs) records machine (`shared-bot` or `thesis-h1-cpu`) as a column, alongside the VM type already logged per cell.
- **Timing:** written before any VM step-8 data exists. Any later change is a further dated amendment.

Sources: `token-efficiency-original-study-2026-10-24.md` (step-8 progress, pending batches, A/A band table), `hard-suite-prereg-v2.md` and `harness-comparison-prereg.md` (amendment format).
