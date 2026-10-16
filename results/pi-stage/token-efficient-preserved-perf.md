# Which Oh My Pi PRs kept pass rate and cut tokens? (2026-10-16)

Source: `pi-stage/scoreboard-omp.csv` (rebuilt from per-run cells on GitHub main: omp-screen5, omp-screen5-b2, omp-cap30-16, omp-cap30-b2, omp-aa28-apikey). Script: `scratch/tep.py`. CSV: `reports/token-efficient-preserved-perf.csv`.
Rules: compare with-PR vs without-PR only within a row. Infra errors and warm-up cells are excluded, and timeouts count as fails. Pass rate counts as "preserved" if Fisher exact p ≥ 0.05 (two-sided). The token bands come from A/A runs: AA [-6.0, +16.3]% for rows before 28, AA2 [-11.4, +6.4]% for rows 28 and later. Cost ($) is never treated as an effect. 5-trial rows are screening only.

## Headline
**No PR is a confirmed token saver with pass rate held.** All 5 rows run at 30 per side kept pass rate (every Fisher p ≥ 0.6). None cut tokens:
- 19: +3.2% [-11.6, +21.0] (+0.1% without the stalled trials). Null.
- 44 (the "dedupe prompt rules" perf PR): +3.3% [-5.4, +13.4]. Its 5-run -13.8% did not hold up.
- 38: +3.5% [-4.0, +13.8]. Its confirmed effect is behavioural (git stash), not tokens.
- 16: **+54.7%** [+44.4, +63.9]. This is a confirmed token *increase*, with pass 30/30 vs 29/30.

**Screening-only leads.** These are 5 runs per side with pass rates unchanged (all at ceiling) and a point estimate below zero. They are not effects.
| Row | PR | Tokens | Status |
|---|---|---|---|
| 44 | dedupe system-prompt rules | -13.8% [-29.3, +4.3] | beyond AA2 lower edge, CI crosses 0. **Refuted at 30/side** |
| 30 | simplified prompt verification/delivery constraints (thinking off) | -10.5% [-16.9, -0.6] | CI below 0 but inside AA2 band. Best untested lead |
| 28 | parallel task delegation wording | -9.5% [-17.0, 0.0] | inside band. Zero task calls both sides, so the change likely never fired |
| 35 | byte-stable system prompt (date/cwd moved out) | -3.2% [-14.4, +12.9] | noise |
| 43 | simplified read-tool prompt (image options removed) | -0.5% [-0.5, -0.5] | tiny. Zero-width CI suggests near-deterministic runs |
| 36 | user-reported-state rule | +0.2% (room report, data lost) | not a cut |

**By kind of PR:** prompt simplification and dedupe PRs (30, 44, 35, 43) lean negative in screening. The only one tested at 30/side (44) came out null. Adding content to the prompt (16 tool descriptions, 21 no-shims rule, 38 testing guidance) raised tokens or did nothing. Nothing shows a reliable savings class yet.

**Suggested next spend:** take row 30 to 30/side (needs thinking off, or a fix for the thinking-signature infra error), and possibly row 28 on a task that actually fans out.

## Ranked-tab draft
Order: rows at 30/side first, then screening rows, each sorted by token delta. **Caveat:** each row builds Oh My Pi at its own parent/merge commit, so each row is its own harness version. Rankings across rows are descriptive only, not a comparison. The A/A band differs before and after row 28. Rows 30, 31, 32 and 19 ran with thinking off.

| Rank | Row | Tier | Pass w/o → with | Fisher p | Tokens Δ [95% CI] | What the PR changed |
|---|---|---|---|---|---|---|
| 1 | 19 @30 excl. trials 16-21 | confirmed-tier | 24/24 → 24/24 | 1 | +0.1% [-13.0, +15.1] | refactor(agent): consolidated and clarified system prompt |
| 2 | 19 @30 (thinking off) | confirmed-tier | 26/30 → 27/30 | 1 | +3.2% [-11.6, +21.0] | refactor(agent): consolidated and clarified system prompt |
| 3 | 44 @30 | confirmed-tier | 27/30 → 29/30 | 0.612 | +3.3% [-5.4, +13.4] | perf(coding-agent/prompts): deduplicate system prompt rules and fix xd:// tool refs |
| 4 | 38 @30 | confirmed-tier | 28/30 → 28/30 | 1 | +3.5% [-4.0, +13.8] | feat(coding-agent/prompts): updated testing guidance in system prompt |
| 5 | 16 @30 | confirmed-tier | 30/30 → 29/30 | 1 | +54.7% [+44.4, +63.9] | feat(coding-agent): enhanced system prompt to include tool descriptions for better clarity |
| 6 | 44 screen (rerun) | screening-only | 5/5 → 5/5 | 1 | -13.8% [-29.3, +4.3] | perf(coding-agent/prompts): deduplicate system prompt rules and fix xd:// tool refs |
| 7 | 30 screen (thinking off) | screening-only | 5/5 → 5/5 | 1 | -10.5% [-16.9, -0.6] | feat(coding-agent/prompts): simplified system prompt verification and delivery constraints |
| 8 | 28 screen | screening-only | 5/5 → 5/5 | 1 | -9.5% [-17.0, +0.0] | feat(coding-agent/prompts): improved parallel task delegation instructions |
| 9 | 35 screen | screening-only | 4/4 → 4/4 | 1 | -3.2% [-14.4, +12.9] | fix(coding-agent): keep the system prompt byte-stable across date/cwd changes |
| 10 | 43 screen | screening-only | 5/5 → 5/5 | 1 | -0.5% [-0.5, -0.5] | feat(coding-agent/prompts): simplified read tool prompt, removing image query options |
| 11 | 39 screen | screening-only | 5/5 → 5/5 | 1 | +0.2% [+0.2, +0.2] | fix(tools): prefer direct image reads for vision-capable models |
| 12 | 32 screen (thinking off) | screening-only | 5/5 → 5/5 | 1 | +0.7% [+0.5, +0.8] | feat(coding-agent/prompts): updated system prompt verification guidelines |
| 13 | 15 / #13 screen | screening-only | 5/5 → 5/5 | 1 | +0.8% [-0.3, +1.8] | fix(system-prompt): remove line causing gpt 5.3 hallucinations |
| 14 | 33 screen | screening-only | 5/5 → 5/5 | 1 | +3.7% [-5.5, +14.0] | feat(coding-agent/tools): updated bash tool prompt to list available shell builtins |
| 15 | 31 screen (thinking off) | screening-only | 4/4 → 3/3 | 1 | +3.9% [-11.8, +28.1] | feat(coding-agent): relaxed bash tool constraints and simplified critical instructions |
| 16 | 38 screen | screening-only | 5/5 → 5/5 | 1 | +11.9% [-1.4, +27.6] | feat(coding-agent/prompts): updated testing guidance in system prompt |
| 17 | 21 screen | screening-only | 5/5 → 5/5 | 1 | +13.0% [+1.1, +27.0] | feat(coding-agent): added coding-agent prompt: no estimates/no shims |
| 18 | 19 screen (thinking off) | screening-only | 5/5 → 5/5 | 1 | +26.8% [+3.0, +60.4] | refactor(agent): consolidated and clarified system prompt |
| 19 | 16 screen | screening-only | 5/5 → 5/5 | 1 | +35.3% [+25.6, +46.4] | feat(coding-agent): enhanced system prompt to include tool descriptions for better clarity |

Not ranked: 36 (data lost, +0.2% per room report), 20/22/45 (not exercisable), and 14 rows still awaiting a screen (14,17,18,23-27,29,34,37,40-42).

## Caveats
- Every screened row has pass at 5/5 vs 5/5 (ceiling), so "preserved" says nothing about harder tasks.
- One model, one trigger task per row. Results may not carry over to other models (e.g. Sonnet) or tasks.
- Row 31 had 3 infra-excluded cells (4 vs 3 left). Row 19 had a shared stall in trials 16-21 (7 timeouts counted as fails).
- The pass-rate test is underpowered at n=5. A drop of 1-2 runs would not reach significance.
- OpenCode is excluded: its per-run data is lost.
