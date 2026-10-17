# Step 3 Sonnet: does the side launched first miss more often?

Written 2026-10-17, 7:20 PM ET, from stored cells only. No benchmark was run and no stored number was changed. Re-run it with `python3 results/step3-sonnet-1016-firstside-fisher/firstside_fisher.py` from the repo root. The script needs only the standard library, since `.venv` has no scipy.

**Answer: no.** In step-3 Sonnet cells run with `--order interleave-seeded --seed 1016`, the side launched first missed **32 of 957** times (3.3%). The second side missed **38 of 953** times (4.0%).

| | miss | solved | total | miss rate |
|---|---|---|---|---|
| first side | 32 | 925 | 957 | 3.3% |
| second side | 38 | 915 | 953 | 4.0% |
| total | 70 | 1840 | 1910 | 3.7% |

- **Pooled Fisher exact test:** two-sided p = 0.47. The one-sided test that the first side misses more gives p = 0.81.
- **Odds ratio, first vs second:** 0.83, 95% CI [0.52, 1.34].
- **Stratified by PR (31 strata):**
  - Mantel-Haenszel OR 0.82 [0.51, 1.35].
  - CMH chi-square p = 0.52 with continuity correction, 0.44 without.
  - Exact conditional test p = 0.46.
- **Power, normal approximation:** at a 3.7% base miss rate, this pool had about 91% power to detect a first-side OR of 2.0, but only about 44% for an OR of 1.5.

## Definitions (same as the runner)
- **First side:** `thesis/ab/run_ab.py` `first_side_for(1016, pr, sides)` returns `sorted(["with","without"])[sha256("1016|first-side|<pr>")[0] % 2]`. It is fixed per PR and stored on every cell as `first_side`. A cell counts as "first" when its side equals `first_side`. Every cell's stored `first_side` and `run_seed` matched the recomputed values: 0 mismatches.
  - In 959 of the 960 trial blocks (pr, task, trial), the first side has the lower `schedule_index`, and in all 960 it has the earlier `started_at`.
  - The one exception is 17098 trial 22. Its "with" cell was quarantined and re-run in a resumed batch, so its index restarted. It still launched about 2 hours after the "without" cell.
- **Judged:** `failure_class` is not one of `infra`, `rate_limited`, `stalled` or `incompatible`. This is the same EX set as `results/step3-sonnet-1016/stats.py`. **Miss:** judged and `success` false (wrong_answer, hang or timeout).
- **Model:** every judged cell has `upstream_model = claude-sonnet-5-5`.

## Data used: canonical scored dir per PR, 31 PRs, 1,920 cells
| dir | PRs |
|---|---|
| step3-sonnet-1016 | 11731 12214 13090 13198 13269 17053 17098 19058 2334 2367 26821 3052 3115 3369 4204 5131 5140 6524 |
| step3-sonnet-1016-reorder | 623 913 984 1248 5066 |
| step3-sonnet-1016-13331-rebuild | 13331 |
| step3-sonnet-1016-23771-lsp | 23771 |
| step3-sonnet-1016-4838-dropblock | 4838 |
| step3-sonnet-1016-make-rebuild2 | 21070 22390 24974 25226 25431 |

The first side is "with" for 17 PRs and "without" for 14. The per-PR counts are in `per_pr.csv`, which splits misses into wrong/hang/timeout and also gives the PR's own pass-rate Fisher p.

**Excluded inside these dirs: 10 infra cells** (3 on the first side, 7 on the second). Details are in `excluded.csv`.
- 3 SSL `WRONG_VERSION_NUMBER` proxy errors: 3115 ×2 and 1248.
- 3 `bun add @ai-sdk/anthropic` setup timeouts: 13269, 3052 and 913.
- 4 runner `no_progress` (300 s idle) stalls: 12214, 13090 and 4838 ×2.

If those 4 stalls were counted as hangs instead, 1 would fall on the first side and 3 on the second. That would push further against a first-side excess.

**Never in these dirs, so not pooled:**
- `step3-sonnet-1016-quarantine`: 17098 with t22 (unmetered), reorder 1248 without t28 (unmetered), and 7 cells of reorder 5066 that failed with Vertex 401/ADC. Each was re-run, and the re-runs are in the canonical data.
- Seeded runs with no usable judged data:
  - `-tempfail`: 11731, 12214 and 13090, which hit the Vertex 400 `temperature` error before #49.
  - `-make-rebuild`: auth failure, all cells infra.
  - `-authsmoke` and `-23771-lsp-smoke`: 1-trial smokes.
- Superseded seeded runs: step3-sonnet-1016/5066 (batch 3), step3-sonnet-1016/4838 (57/60 infra) and make-rebuild2/23771 (2+2 timeouts, no C# LSP). These are used only in S4 below.

**Skipped because they were not run in seeded order:**
- step3-sonnet-1016/623, 913, 984 and 1248: OLD ORDER `--order interleave`, with "without" always first. All were re-run in seeded order in `-reorder`.
- step3-sonnet-1016-oldorder-partial/2334: OLD ORDER, partial. Re-run in seeded order.
- step3-sonnet-1016-sidesorder-aborted/623, 913 and 984: `--order sides`, which is block order. Aborted.

## Sensitivity checks (full numbers in output.txt and results.json)
| check | first miss | second miss | OR (MH) | Fisher p | CMH p (cc) | exact cond. p |
|---|---|---|---|---|---|---|
| Primary | 32/957 | 38/953 | 0.82 | 0.47 | 0.52 | 0.46 |
| S1: drop 3052 (only PR with own pass-rate p<0.05) | 31/927 | 31/924 | 1.00 | 1.00 | 0.90 | 1.00 |
| S2: hangs + timeouts only | 24/949 | 19/934 | 1.25 | 0.54 | 0.58 | 0.53 |
| S3: wrong answers only | 8/933 | 19/934 | 0.40 | 0.051 | 0.046 | 0.042 |
| S3b: wrong answers only, drop 3052 | 8/904 | 12/905 | 0.65 | 0.50 | 0.50 | 0.49 |
| S4: + superseded seeded runs | 34/987 | 41/987 | 0.80 | 0.48 | 0.45 | 0.39 |
| S5: + OLD-ORDER runs (first = without) | 37/1097 | 45/1092 | 0.80 | 0.37 | 0.40 | 0.35 |

S3's borderline result goes the opposite way: the second side had more wrong answers, not fewer. It comes entirely from 3052. Its first side is "with", and the "without" (parent) side gave 7 wrong answers because of the image-read bug the PR fixes. Without 3052 the result is p = 0.50.

## Caveats
1. **Side and arm are the same thing within a PR.** For any one PR, "first" is always the same arm, so a first-side effect can only be separated from PR effects by comparing PRs that put "with" first against PRs that put "without" first. This assumes PR effects on pass rate roughly cancel out or are rare.
   - 3052 is a real PR effect. S1 removes it and gives OR = 1.00.
   - For context, the same cells split by arm instead of position give 27/954 misses on "with" vs 43/956 on "without": MH OR 0.60, CMH p = 0.06 (cc).
2. **"First" here means a head start of a few seconds, not a cold block.** The runner launched both sides of a trial block within a median of 4 s of each other. In 871 of 960 blocks, the second side started before the first had finished. So this tests position inside the pair under interleaving. It does not test the cold-first-block mechanism behind the 7 first-block misses in the block-ordered Sonnet A/A, because no step-3 seeded run had a cold block.
3. **Misses are rare.** There were 70 misses, 39 of them in 5 PRs (984, 13269, 3052, 4204, 1248), and 16 PRs had none. The test can rule out a large first-side effect (OR ≥ 2), but not a small one (OR ≈ 1.5).
4. **Which dir counts for each PR follows the step-3 summaries.** The latest seeded re-run is taken as the scored one. S4 shows that adding the superseded seeded runs changes nothing.
