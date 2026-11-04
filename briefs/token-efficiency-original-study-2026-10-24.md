# Token Efficiency of OpenCode Harness Changes: The Original A/B Study

*Sean Lai (NYU). Brief for Prof. João Sedoc, 2026-10-24. Covers the original study only. The later hard-suite (H2), hard-task, and five-harness work is reported separately.*

## Summary
We asked whether individual merged pull requests to the OpenCode agent harness change the number of LLM tokens an agent uses on a fixed task, and whether they change its success rate. Each PR was built into two harnesses, one with the change and one without it. We ran each harness on a task chosen to exercise the change, 30 trials per side, using Claude Sonnet 5.5 and Claude Opus 5.5 served on GCP Vertex. Every model request went through a metering proxy. The first A/B stage closed on 2026-10-07 with its scoreboard frozen at openbench `main` b3cdbee (PR #21), at an OpenCode spend of $1,084.99. It reported four PRs with a token-efficiency effect (26821, 913, 3052, 13331) and two with a behavioural effect (24974, 25226). The 30-per-side reconfirmation then ran on 31 PRs on Sonnet and 31 PRs on Opus. Three token effects replicate on both models: #3052 (−64.8% on Sonnet, −51.8% on Opus), #13331 (−27.9% / −25.5%), and #26821 (−26.5% / −26.9%). PR #913 is an effect only on Opus, and in the opposite direction (+23.4%). Both behavioural effects replicate with large effect sizes on Opus and on Sonnet. The full Sonnet run over the 413 remaining harness PRs is partial: 56 of 351 runnable PRs have been scored, and four of them show a small token effect. The Opus check sample has not been run yet.

## Question
Does a single harness change (for example, prompt text, tool output handling, or image handling) measurably change the tokens an agent spends on a task, and does it change whether the task is solved? We take an effect to be real only when it exceeds the noise of the measurement pipeline itself, which we quantify with A/A runs.

## Setup
- **Models:** Claude Sonnet 5.5 and Claude Opus 5.5 on GCP Vertex AI. All traffic goes through a local metering proxy that writes a per-request ledger. The upstream model is recorded on every cell.
- **Harness:** OpenCode (repository `anomalyco/opencode`). For each PR, the "with" side is built at the merge and the "without" side is the same tree with that PR's change removed. "Strip" marks cases where a block had to be removed by hand.
- **PR inventory:** 1,963 merged PRs touch harness paths. Of these, 447 were judged testable: 209 conditional, 185 always-on, and 53 that need a new task. The first stages used 34 of them. The remaining 413 form the full-run scope; 62 of those were skipped, mostly because no runnable task exists, which leaves 351 to run in 16 batches.
- **Tasks:** OpenBench tasks. Generic tasks include `make-it-run`, `make-ci-green`, and `taskflow`. Targeted trigger tasks are written so the changed code path actually fires, for example `trig-image-read`, `trig-todo-task`, and `trig-webfetch-image`.
- **Sides and seeds:** 30 trials per side. Order is `--order interleave-seeded --seed 1016` (seed 1016 for Sonnet and A/A; Opus step 6 used its own 1017 batch directories).

## Methods
- **Token metric:** input (uncached) + output + cache-read + cache-write tokens, summed over every proxy request in a trial. Cells marked infra, hang, rate-limited, stalled, or incompatible are excluded from the judged set, and counts are reported per side.
- **Interval:** bootstrap 95% percentile CI (10,000 resamples) on the relative difference in mean tokens, (with − without) / without.
- **Token effect rule:** the CI excludes 0 **and** the point estimate lies outside the A/A noise band for that model and harness. A CI that excludes 0 with a point estimate inside the band is labelled "no effect detected (inside A/A band)". Labels in the attached CSV were recomputed with this rule from the raw summary lines. A few early Sonnet summary lines printed "effect" under an older rule; for example, #913 at −2.7% and #19058 at −0.1% are both inside the band.
- **Pass rate:** Fisher exact test, two-sided, solved vs not solved. A gain with 0.01 < p < 0.05 is labelled *borderline*.
- **A/A noise bands** (identical harness on both sides):

| Model | Harness | Δ tokens [95% CI] | Notes | Cost |
|---|---|---|---|---|
| Sonnet 5.5 | OpenCode | +0.1% [−6.5%, +6.8%] | 26 non-hang vs 30 | $28.27 (both harnesses) |
| Sonnet 5.5 | Oh My Pi | +4.1% [−3.4%, +14.0%] | | (incl. above) |
| Opus 5.5 | OpenCode | −3.2% [−10.4%, +4.4%] | 30/30 pass each side | $29.12 |
| Opus 5.5 | Oh My Pi | +1.1% [−5.9%, +8.8%] | 30/30 pass each side | $33.36 |

- **First-side rule retired (PR #89):** An earlier rule discarded the first-run side as possibly disadvantaged. We tested this on 31 PRs (1,920 cells, 10 infra excluded). First-side failures were 32/957 (3.3%) against 38/953 (4.0%) for the second side. Fisher p = 0.47, OR 0.83 [0.52, 1.34]. The stratified Mantel–Haenszel OR was 0.82 [0.51, 1.35], CMH p = 0.52. Power to detect an OR of 2.0 was about 91%, and about 44% for an OR of 1.5. On this basis the rule was retired for interleaved runs.

## Results

### Stage 1 (frozen scoreboard, b3cdbee / PR #21)
Token-efficiency effects: #26821, #913, #3052, #13331. Behavioural effects: #24974 (prompt rule order) and #25226 (tmpdir handling). Spend was $1,084.99 of a $3,000 budget. That figure covers OpenCode only; the Oh My Pi runs spent about $165 more. Source: `reports/findings.html` (2026-10-16), section 3. The 30-per-side reconfirmation below supersedes the Stage-1 estimates.

### Reconfirmation at 30 per side (the six headline PRs)

| PR | Task | Sonnet pass w/o→w | Sonnet Δ tokens [95% CI] | Opus pass w/o→w | Opus Δ tokens [95% CI] |
|---|---|---|---|---|---|
| 3052 | trig-image-read | 22/29 → 29/30 (Fisher p = 0.026, borderline) | **−64.8% [−66.7, −62.6]** | 29/30 → 29/30 | **−51.8% [−56.2, −47.9]** |
| 13331 | trig-webfetch-image | 30/30 → 30/30 | **−27.9% [−32.1, −22.8]** | 30/30 → 30/30 | **−25.5% [−30.2, −20.5]** |
| 26821 | trig-todo-task | 28/30 → 28/30 | **−26.5% [−34.0, −18.0]** | 28/30 → 28/30 | **−26.9% [−34.3, −18.9]** |
| 913 | trig-list-noise | 30/30 → 29/29 | −2.7% [−6.2, −0.6] (inside band) | 30/30 → 30/30 | **+23.4% [+17.3, +29.6]** |
| 24974 | trig-prompt-order | 30/30 → 30/30 | −2.9% [−6.4, +0.6] | 28/29 → 28/30 | −6.6% [−14.9, +2.8] |
| 25226 | trig-tmpdir | 25/30 → 29/30 (p = 0.19) | +14.1% [−0.9, +32.2] | 26/28 → 27/30 | +13.8% [−1.1, +30.3] |

Behavioural measures (Fisher, two-sided):
- **#24974**, global rule followed first:
  - Sonnet: 0/30 without vs 30/30 with, p = 1.7e−17.
  - Opus: 1/29 vs 21/30, p = 6.1e−08.
- **#25226**, Opus:
  - Temp-dir leak: 21/28 → 0/30 (p = 3.5e−10).
  - Permission rejections: 20/28 → 0/30 (p = 1.7e−09).
  - Solved: p = 1.
- **#25226**, Sonnet: the effect is strong on the most direct measure. The temp dir leaked into the workspace in 10/30 trials without the change and 0/30 with it (p ≈ 0.0008). Source: `results/step3-sonnet-1016-make-rebuild2/25226/{without,with}.jsonl` in `sean-lai-sh/openbench` (data PR #75, commit d7462cd880); the count is cells with `tmpdir_leaked_dirs` > 0. As noted in `results/d1-25226-split-1022/NOTE-D1-1022.md`, this headline leak count deliberately excludes `$TMPDIR/opencode`. The secondary measures are weaker: ended on a permission rejection 5/30 → 0/30 (p = 0.052, borderline), complete answer 24/30 → 29/30 (p = 0.10).

### The other PRs from the first stages (30 per side)
- **Sonnet:** 31 PRs total. Of the 25 besides the six above, none shows a token effect under the rule, and none shows a pass-rate effect. Three are inside-band results: #2367, #5066, #19058.
- **Opus:** 31 PRs total. Three additional PRs show Opus-only token effects:
  - #13090 (trig-read-edge): −16.9% [−26.6, −7.0].
  - #5140 (trig-workdir): −13.6% [−21.3, −4.5].
  - #4204 on its `trig-subagent-resume` task: +25.0% [+16.0, +33.5]. Pooled over both #4204 tasks the result is +8.6% [−4.4, +23.8], no effect.
  
  None of the three was flagged on Sonnet. They come from single runs and should be read as candidates. No Opus pass-rate test reached p < 0.05.

All per-PR rows are in the CSV.

### Full 413-PR Sonnet run (step 8): partial
- **Progress:** 56 PRs fully scored at 30/side out of 351 runnable. These are the 9-PR pilot (#107), batches F01 and F02, and part of F03. A disk-space guard repeatedly stopped the runner. PRs #950 and #3185 are only partly run and are left unscored.
- **Results:**
  - Pass-rate effects: none in the 56 scored PRs.
  - Token effects under the rule: four, all modest. #795 +18.3% [+2.0, +37.3]; #1109 −6.9% [−11.9, −1.7]; #1443 +11.3% [+2.0, +22.8]; #2051 −7.5% [−12.9, −1.9].
  - The other 52 show no effect, two of them inside the band.
- **Pending:** batches F03 (remainder) through F16, which is about 295 PRs.

### Opus follow-up and check sample: pending
- **Plan:** Opus runs only for PRs with a Sonnet signal, plus a check sample of 40 PRs with no Sonnet signal, capped at $1.2K.
- **Check sample drawn:** seed 20261016, 50 drawn (21 always-on / 23 conditional / 6 needs-new-task). The first 40 in draw order with no Sonnet signal form the sample. The list is fixed in `opus-check-sample.csv`, sha256 prefix f6a180f4.
- **Status:** no Opus check-sample results exist yet.

## Cost

| Item | Cost |
|---|---|
| Stage 1 (to scoreboard freeze) | $1,084.99 for OpenCode, plus about $165 for Oh My Pi (`reports/findings.html`, §3) |
| A/A Sonnet (OpenCode + Oh My Pi) | $28.27 |
| A/A Opus (OpenCode / Oh My Pi) | $29.12 / $33.36 |
| Step 3, Sonnet reconfirmation | $323.35 total: $283.96 on the 'OpenCode Sonnet' tab plus $39.39 on the 'Set-aside runs' tab. The scored rows in the CSV sum to $251.07. The $72.28 gap is $32.89 of superseded runs plus $39.39 of excluded failed, aborted and smoke runs. |
| Step 6, Opus reconfirmation | $536.06 (sum of canonical rows in the CSV) |
| Step 8, Sonnet full run, 56 scored PRs | $272.60 (sum of scored rows) |

## Limitations
- There is one task per PR in most cases, so an effect is specific to that task. A null result means "no effect on this trigger", not "no effect anywhere".
- Each estimate comes from a single run at 30 per side with no correction for multiple comparisons. Across roughly 120 PR-model tests, a few false positives are expected. The three Opus-only and four step-8 effects need replication.
- The A/A bands come from one 30-vs-30 run each, and the Sonnet OpenCode band has 4 hang exclusions.
- Some "without" builds needed a hand-removed block ("strip"), which could add noise beyond the PR itself.
- Pass rates on many tasks are at the ceiling (30/30), so the pass-rate tests have little power.

## Data and code
- Repository: OpenBench (`sean-lai-sh/openbench`), at `main` 6f29468f when this brief was compiled.
- Scoreboard freeze: b3cdbee (PR #21).
- A/A: `results/aa-sonnet-1016/SUMMARY.txt` and PRs #85 and #86.
- First-side test: PR #89 and `results/step3-sonnet-1016-firstside-fisher/`.
- Sonnet 30/side: `results/step3-sonnet-1016*/`. Behaviour measures are in PR #75 (`BEHAVIOUR-24974-25226.txt`).
- Opus 30/side: `results/step6-opus-1017-*/` (PRs #77–#84 and #96–#101).
- Step 8: `results/step8-sonnet447-pilot-1020-full/` and `results/step8-full413-1020*/` (PRs #107, #109/#110, #116/#117, #120, #122).
- Per-PR table: `token-efficiency-original-study-2026-10-24.csv`.
