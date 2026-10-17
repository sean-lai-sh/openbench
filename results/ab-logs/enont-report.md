# ENOENT-set A/B report (@ 019ad6e / PR #8)

Generated 2026-10-05T17:56:41-04:00 (driver end) + monitor addendum 18:01 ET.
Driver: `bash results/ab-logs/enont-driver.sh`. Note: driver attempted to write this file but the embedded summary Python hit `SyntaxError: def dlt$` — base table reconstructed from `enont-posts/` + live cells; sections below are monitor-authored.

## Researcher scoring lock
- Primary: pass, wall, output tokens, tokens_input_uncached (non-cache input).
- Secondary: blended $/cell — FLAG when |billable tok Δ% − cost Δ%| > 5pp; then require bucket table.
- No CLEAR claims for mid-era ENOENT rows.

## Summary table

| PR | n | Pass | Wall Δ% | Out tok | Noncache in | Tok/cell Δ% | $/cell Δ% | Metering | Notes |
|---|---|---|---|---|---|---|---|---|---|
| 4838 (smoke) | 24/24 | 1.000→1.000 | +4.5% | (see smoke-4838.md) | (see smoke) | +21.6% | -1.7% | proxy_measured | CR=0 |
| 4204 | 24/24 | 0.000→0.000 | -13.4% | 14.9→14.9 | 4.0→4.0 | -0.0% | -6.4% | proxy 22/22 | infra deaths; FLAG 6.4pp |
| 5066 | 24/24 | 1.000→1.000 | -7.7% | 4650→4409 | 15.7→15.3 | -9.6% | -12.6% | proxy_measured | CR=0 |
| 5131 | 24/24 | 1.000→1.000 | +4.3% | 4645→4875 | 15.7→16.8 | +16.4% | -4.4% | proxy_measured | FLAG 20.7pp |
| 5140 | 24/24 | 1.000→1.000 | +3.4% | 4614→4723 | 15.4→16.2 | +10.4% | +54.8% | proxy_measured | FLAG 44.4pp |
| 5527 | 24/24 | 1.000→1.000 | +1.1% | 4778→4603 | 16.5→15.8 | -9.6% | -1.3% | proxy_measured | FLAG 8.4pp |
| 6524 | 24/24 | 1.000→1.000 | -11.8% | 4954→4543 | 16.9→15.8 | -17.0% | -3.3% | proxy_measured | FLAG 13.7pp; toolchain ai=5.0.97 anthropic=2.0.0 bun=1.3.5; CR=0 |

## Spend
- Driver latest (`enont-latest.txt`): `done spend=$558.80`
- `python3 results/ab-logs/hard5_stats.py total` (sum of row_cost over all `results/ab/*/cells`): **$624.10**
- Soft pause $700 (not hit).

## Notes
- Group posts: `results/ab-logs/enont-posts/` (do not post from executor; Thesis Developer relays).
- Quarantine / progress: `enont-progress.md`.

---

## Bucket tables

Computed with `from thesis.ab.summarize import billable_tokens, row_cost, RATES` over `results/ab/<pr>/cells/{without,with}/*/*.json` (per-cell means).

### PR #5140

RATES $/MTok: `{'tokens_input_uncached': 4.0, 'tokens_output': 20.0, 'tokens_cache_read': 0.2, 'tokens_cache_write': 5.0}`

| side | n | uncached_in | output | cache_read | cache_write | billable | $/cell |
|---|---|---|---|---|---|---|---|
| without | 24 | 15.4 | 4613.5 | 163383.7 | 25846.7 | 193859 | 0.2542 |
| with | 24 | 16.2 | 4723.0 | 155626.3 | 53571.6 | 213937 | 0.3935 |

| side | $uncached | $output | $cache_read | $cache_write |
|---|---|---|---|---|
| without | $0.0001 | $0.0923 | $0.0327 | $0.1292 |
| with | $0.0001 | $0.0945 | $0.0311 | $0.2679 |

Δ$ attribution (with−without):
- `tokens_input_uncached`: 15.4→16.2 (+5.4%)  $0.0001→$0.0001 (Δ$+0.0000)
- `tokens_output`: 4613.5→4723.0 (+2.4%)  $0.0923→$0.0945 (Δ$+0.0022)
- `tokens_cache_read`: 163383.7→155626.3 (-4.7%)  $0.0327→$0.0311 (Δ$-0.0016)
- `tokens_cache_write`: 25846.7→53571.6 (+107.3%)  $0.1292→$0.2679 (Δ$+0.1386)
- headline billable 193859→213937 (+10.4%)  $/cell 0.2542→0.3935 (+54.8%)  |gap|=44.4pp
- **READ:** $ gap driven mainly by `tokens_cache_write` (Δ$+0.1386, 100% of ΣΔ$)

### PR #5131

RATES $/MTok: `{'tokens_input_uncached': 4.0, 'tokens_output': 20.0, 'tokens_cache_read': 0.2, 'tokens_cache_write': 5.0}`

| side | n | uncached_in | output | cache_read | cache_write | billable | $/cell |
|---|---|---|---|---|---|---|---|
| without | 24 | 15.7 | 4645.5 | 156750.2 | 28694.9 | 190106 | 0.2678 |
| with | 24 | 16.8 | 4874.5 | 192333.1 | 24022.8 | 221247 | 0.2561 |

| side | $uncached | $output | $cache_read | $cache_write |
|---|---|---|---|---|
| without | $0.0001 | $0.0929 | $0.0314 | $0.1435 |
| with | $0.0001 | $0.0975 | $0.0385 | $0.1201 |

Δ$ attribution (with−without):
- `tokens_input_uncached`: 15.7→16.8 (+6.9%)  $0.0001→$0.0001 (Δ$+0.0000)
- `tokens_output`: 4645.5→4874.5 (+4.9%)  $0.0929→$0.0975 (Δ$+0.0046)
- `tokens_cache_read`: 156750.2→192333.1 (+22.7%)  $0.0314→$0.0385 (Δ$+0.0071)
- `tokens_cache_write`: 28694.9→24022.8 (-16.3%)  $0.1435→$0.1201 (Δ$-0.0234)
- headline billable 190106→221247 (+16.4%)  $/cell 0.2678→0.2561 (-4.4%)  |gap|=20.7pp
- **READ:** $ gap driven mainly by `tokens_cache_write` (Δ$-0.0234, 200% of ΣΔ$)

### PR #5527

RATES $/MTok: `{'tokens_input_uncached': 4.0, 'tokens_output': 20.0, 'tokens_cache_read': 0.2, 'tokens_cache_write': 5.0}`

| side | n | uncached_in | output | cache_read | cache_write | billable | $/cell |
|---|---|---|---|---|---|---|---|
| without | 24 | 16.5 | 4778.2 | 158747.7 | 60448.0 | 223990 | 0.4296 |
| with | 24 | 15.8 | 4602.5 | 136907.2 | 60948.5 | 202474 | 0.4242 |

| side | $uncached | $output | $cache_read | $cache_write |
|---|---|---|---|---|
| without | $0.0001 | $0.0956 | $0.0317 | $0.3022 |
| with | $0.0001 | $0.0921 | $0.0274 | $0.3047 |

Δ$ attribution (with−without):
- `tokens_input_uncached`: 16.5→15.8 (-4.5%)  $0.0001→$0.0001 (Δ$-0.0000)
- `tokens_output`: 4778.2→4602.5 (-3.7%)  $0.0956→$0.0921 (Δ$-0.0035)
- `tokens_cache_read`: 158747.7→136907.2 (-13.8%)  $0.0317→$0.0274 (Δ$-0.0044)
- `tokens_cache_write`: 60448.0→60948.5 (+0.8%)  $0.3022→$0.3047 (Δ$+0.0025)
- headline billable 223990→202474 (-9.6%)  $/cell 0.4296→0.4242 (-1.3%)  |gap|=8.4pp
- **READ:** $ gap driven mainly by `tokens_cache_read` (Δ$-0.0044, 81% of ΣΔ$)

### PR #6524

RATES $/MTok: `{'tokens_input_uncached': 4.0, 'tokens_output': 20.0, 'tokens_cache_read': 0.2, 'tokens_cache_write': 5.0}`

| side | n | uncached_in | output | cache_read | cache_write | billable | $/cell |
|---|---|---|---|---|---|---|---|
| without | 24 | 16.9 | 4953.5 | 175906.7 | 58112.8 | 238990 | 0.4249 |
| with | 24 | 15.8 | 4543.1 | 135290.9 | 58610.0 | 198460 | 0.4110 |

| side | $uncached | $output | $cache_read | $cache_write |
|---|---|---|---|---|
| without | $0.0001 | $0.0991 | $0.0352 | $0.2906 |
| with | $0.0001 | $0.0909 | $0.0271 | $0.2931 |

Δ$ attribution (with−without):
- `tokens_input_uncached`: 16.9→15.8 (-6.9%)  $0.0001→$0.0001 (Δ$-0.0000)
- `tokens_output`: 4953.5→4543.1 (-8.3%)  $0.0991→$0.0909 (Δ$-0.0082)
- `tokens_cache_read`: 175906.7→135290.9 (-23.1%)  $0.0352→$0.0271 (Δ$-0.0081)
- `tokens_cache_write`: 58112.8→58610.0 (+0.9%)  $0.2906→$0.2931 (Δ$+0.0025)
- headline billable 238990→198460 (-17.0%)  $/cell 0.4249→0.4110 (-3.3%)  |gap|=13.7pp
- **READ:** $ gap driven mainly by `tokens_output` (Δ$-0.0082, 59% of ΣΔ$)

---

## Exercised check

### #4838 — compaction prompt (`session/compaction.ts`, `session/prompt/compaction.txt`)

- **Change:** rewrite of compaction user prompt + `compaction.txt` sections (persistent constraints / technical decisions). Trigger unchanged.
- **Trigger (`SessionCompaction.isOverflow`):** `count = tokens.input + tokens.cache.read + tokens.output`; fires when `count > model.limit.context - min(model.limit.output, OUTPUT_TOKEN_MAX)` with `OUTPUT_TOKEN_MAX=32_000` (`packages/opencode/src/session/prompt.ts`). Also publishes `session.compacted`. Prune path: `PRUNE_PROTECT=40_000` / `PRUNE_MINIMUM=20_000` tool-output token estimates.
- **SHAs:** without `ff609a52…` / with `aaa31f02…` (worktrees under `results/opencode-src/worktrees/`).
- **Evidence scan:** all 48 cell JSON `output_tail` + `usage_raw` under `results/ab/4838/cells/{without,with}/` — no matches for `compact|summariz|session.compacted|compaction|context-overflow|Continue if you have next steps`. No sharp mid-run `cache.read` collapse heuristic hits.
- **Max per-request overflow count (`in+cache_read+out`):** without **61387**; with **71354**. Cell field `model_context_window=None`; model id `claude-opus-5-5` (Opus 5.5 class → **1M** context per Anthropic docs) ⇒ usable ≈ **1_000_000 − 32_000 = 968_000**. Even under a conservative 200k context (usable 168k), observed max ≪ threshold.
- **Label:** **not exercised** on both sides (0/24 without, 0/24 with). Compaction prompt never ran; A/B cannot speak to prompt quality.

### #4204 — task tool resume (`tool/task.ts` session_id)

- **Change:** optional `session_id` on task tool to resume a subagent session; output gains `<task_metadata>session_id: …</task_metadata>` (with SHA `0d3d48bb…`).
- **Cell outcome:** pass 0→0; classes infra 22 + incompatible 2 per side; mean wall ~5.7s→5.0s; `turns=None` all cells. `output_tail` dies immediately after `step_start` with `UnknownError: Unhandled chunk type: custom` (e.g. `results/ab/4204/cells/with/make-it-run/1.json`).
- **Evidence scan:** no `task` / `task_metadata` / `session_id` resume hits in any of 48 tails.
- **Label:** **undeterminable** (0 fired / 0 not-fired / 24 undet per side). Infra abort before tools; check not possible on this cohort.

### Evidence path roots
- Cells: `results/ab/4838/cells/`, `results/ab/4204/cells/`
- Source: `results/opencode-src/worktrees/<sha>/packages/opencode/src/…`
- Posts: `results/ab-logs/enont-posts/`, `results/ab-logs/smoke-4838.md`

