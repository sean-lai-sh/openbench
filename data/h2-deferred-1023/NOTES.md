# H2 deferred rerun 2026-10-23

## Smoke gate (required before batch)
Both smokes PASS in `results/h2-pin-smoke-1023b/`:
- opus/4204 → `@ai-sdk/anthropic` **2.0.0**, no sdk drift
- sonnet/13331 → `@ai-sdk/anthropic` **2.0.77**, no sdk drift
Runner for deferred batch: `e2ac6b75` (PR #126 pin fix). Finished H2 cells in `h2-hardsuite-1022` stay on runner `980e71b6` (untouched).

## Batch
- Out: `h2-deferred-1023` on VM `thesis-h1-cpu`, image `h2-env:1022`, seed 1022, jobs 4
- Deferred rows: Sonnet 13331, 26821, 11731; Opus 4204, 5140, 13090, 13331, 26821
- Planned: 8 × 180 = 1440 cells (9 tasks × 10 trials × 2 sides)
- (fill on completion)

## Scoring
A2 via `an_a2.py` + per-row pooled mean tokens with 95% bootstrap CI (10k seed 0) on scored cells only.
Transcripts left on VM; see MANIFEST-transcripts.txt.
