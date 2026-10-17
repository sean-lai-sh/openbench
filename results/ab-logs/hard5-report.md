# Harder-task 5-trial A/B report (@ e04d456 / PR #6)

Generated 2026-10-05T17:00:03-04:00 (driver) + monitor addendum 17:02 ET. Soft cap CAP=$700. See also hard5-progress.md.

## Researcher scoring lock (apply to all claims)
- **Primary:** pass rate, wall, **output tokens**, **tokens_input_uncached** (non-cache input).
- **Secondary:** blended $/cell — any $ CLEAR needs bucket table (in/out/cache_read/cache_write + $).
- #26821 stays **unconfirmed** (tok up / cost down; first-pass didn't replicate).
- #3115 dropped from any CLEAR claim until tok and cost move together.
- Noise floor ±12% wall / ±19% billable tok / ±11% cost applies only to #26821/#13331/#23771.
- FLAG when |billable tok Δ% − cost Δ%| > 5pp.

## Primary metrics (5-trial means, vendor_split)

| PR | Pass | Wall Δ% | Output tok Δ% | input_uncached Δ% | $/cell Δ% (2°) | Billable tok Δ% | |tok−$| pp | Verdict |
|---|---|---|---|---|---|---|---|---|
| 26821 | 1.000→1.000 | +9.5% | +14.7% | +13.0% | -15.1% | +7.8% | 22.9 | UNCONFIRMED — $−15% vs billable +7.8%/output +14.7%; cache_write −26% drives $; do not claim harness win |
| 13331 | 0.900→0.900 | +5.5% | -45.1% | -10.6% | -14.2% | -17.4% | 3.2 | Mixed — pass flat; wall within floor; **output −45%** (primary); $−14% secondary mostly from output (93% of Δ$); cache_w flat |
| 23771 | 1.000→1.000 | +17.9% | +21.0% | +3.2% | +7.5% | +7.3% | 0.1 | Not a win — pass flat; wall **+17.9%** outside floor; output **+21%**; $ +7.5% tracks billable (+7.3%) |
| 2334 | 0.000→0.000 | -9.5% | -12.4% | +0.0% | -32.2% | -0.1% | 32.0 | NOT CLEAR — pass 0→0; |tok−$|=32pp; Δ$ ≈100% cache_write; tiny fail cohort |
| 3115 | 0.000→0.000 | -4.2% | +3.5% | +0.0% | -8.9% | +0.1% | 8.9 | NOT CLEAR — pass 0→0; |tok−$|=8.9pp; Δ$ ≈ cache_write; drop from CLEAR claims |

## Spend
- Prior (pre-hard5): $432.34
- Hard5 phase new: **+$97.32**
- Cumulative all phases: **$529.66** (under $700 soft pause; no pause triggered)
- Per-PR $: 26821 $25.70; 13331 $31.96; 23771 $33.48; 2334 $2.70; 3115 $3.48

## Bucket breakouts (on disk)
- results/ab-logs/hard5-26821-token-cost-buckets.md (posted by parent)
- results/ab-logs/hard5-13331-token-cost-buckets.md
- results/ab-logs/hard5-23771-token-cost-buckets.md
- results/ab-logs/hard5-2334-token-cost-buckets.md
- results/ab-logs/hard5-3115-token-cost-buckets.md

## Group posts drafted (executor lacks SendToAgent)
- results/ab-logs/hard5-group-posts/{13331,23771,2334,3115}.txt + final-summary.txt
- Parent: SendToAgent → Senior Thesis `7eed13d4-27d6-4739-acfd-0f1c0d3febc7` priority false
- Do NOT repost #26821

---

# Harder-task 5-trial A/B report (auto-generated)

Worktree /workspace/openbench-ab @ e04d456 (PR #6). Driver: results/ab-logs/hard5.sh. Command: `python3 -m thesis.ab.run_ab thesis/ab/fixtures/opencode-harness-prs.csv --pr <PR> --trials 5 --jobs 8 --out results/ab --cache /workspace/openbench-ab/results/opencode-src` (all 8 core tasks).

PRs: first-pass clears 26821, 13331, 23771; set-aside tiny-cell cohort 2334, 3115 (3-trial CLEAR not confirmed under first-pass A/A floor).

Cumulative est. spend (all phases): $529.66 (prior pre-hard5 $432.34 + hard5 new $97.32). Soft pause ~$700.

Noise floor (first-pass A/A+controls): ±12% wall, ±19% tokens, ±11% cost. CLEAR = outside band for first-pass PRs. Tiny-cell set-aside PRs marked with * — band shown for reference only.

Token vs cost: report both Δ% side by side. FLAG when |tok Δ% − cost Δ%| > 5pp (metering/counting suspicion).

| PR | n (b/a) | Pass b→a | Wall s b→a (Δ%) | Turns b→a | Tok/cell b→a (Δ%) | $/cell b→a (Δ%) | PR $ | SDK changed | vs noise |
|---|---|---|---|---|---|---|---|---|---|
| 26821 | 40/40 | 1.000→1.000 | 42.4→46.4 (+9.5%) | 5.2→6.0 | 146k→157k (+7.8%) | 0.347→0.295 (-15.1%) | 25.70 |  | CLEAR; tok/cost DISAGREE |
| 13331 | 40/40 | 0.900→0.900 | 118.0→124.5 (+5.5%) | 5.9→5.8 | 166k→137k (-17.4%) | 0.430→0.369 (-14.2%) | 31.96 |  | CLEAR |
| 23771 | 40/40 | 1.000→1.000 | 70.9→83.6 (+17.9%) | 6.0→6.3 | 180k→193k (+7.3%) | 0.403→0.434 (+7.5%) | 33.48 |  | CLEAR |
| 2334 | 40/40 | 0.000→0.000 | 5.0→4.5 (-9.5%) | n/a→n/a | 16k→16k (-0.1%) | 0.040→0.027 (-32.2%) | 2.70 |  | CLEAR* (tiny-cell cohort; first-pass A/A ±12/±19/±11 not applied as confirmed floor); tok/cost DISAGREE |
| 3115 | 40/40 | 0.000→0.000 | 5.1→4.8 (-4.2%) | n/a→n/a | 16k→16k (+0.1%) | 0.046→0.042 (-8.9%) | 3.48 |  | within* (tiny-cell cohort; first-pass A/A ±12/±19/±11 not applied as confirmed floor); tok/cost DISAGREE |

## Clears noise floor (first-pass cohort only)
26821, 13331, 23771

## Token vs cost disagreement flags

### PR 26821
- PR-aggregate token Δ% (+7.8%) vs cost Δ% (-15.1%) disagree by 22.9pp (>5pp) — likely metering/counting, not harness
- task add-feature: tok Δ%=-4.7% cost Δ%=-23.8% (disagree 19.1pp); fail n 0→0
- task fix-failing-test: tok Δ%=-36.5% cost Δ%=-41.6% (disagree 5.1pp); fail n 0→0
- task make-ci-green: tok Δ%=-38.6% cost Δ%=-44.8% (disagree 6.1pp); fail n 0→0
- task make-it-run: tok Δ%=-27.6% cost Δ%=-20.9% (disagree 6.7pp); fail n 0→0
- task taskflow: tok Δ%=+25.1% cost Δ%=-8.2% (disagree 33.3pp); fail n 0→0
- task webcore: tok Δ%=+24.6% cost Δ%=+9.3% (disagree 15.3pp); fail n 0→0
### PR 13331
- task build-a-cli: tok Δ%=-9.2% cost Δ%=+14.0% (disagree 23.2pp); fail n 0→0
- task fix-failing-test: tok Δ%=+4.5% cost Δ%=+10.4% (disagree 5.9pp); fail n 0→0
- task make-it-run: tok Δ%=-0.2% cost Δ%=+14.9% (disagree 15.1pp); fail n 0→0
- task taskflow: tok Δ%=+7.0% cost Δ%=+0.4% (disagree 6.6pp); fail n 0→0
- task webcore: tok Δ%=-45.0% cost Δ%=-50.5% (disagree 5.5pp); fail n 4→4
### PR 23771
- task add-feature: tok Δ%=+9.0% cost Δ%=-10.0% (disagree 19.1pp); fail n 0→0
- task build-a-cli: tok Δ%=+0.2% cost Δ%=+31.4% (disagree 31.3pp); fail n 0→0
- task make-it-run: tok Δ%=-4.6% cost Δ%=+4.7% (disagree 9.3pp); fail n 0→0
- task misleading-error: tok Δ%=-5.8% cost Δ%=-18.3% (disagree 12.5pp); fail n 0→0
- task taskflow: tok Δ%=-7.8% cost Δ%=+5.8% (disagree 13.6pp); fail n 0→0
### PR 2334
- PR-aggregate token Δ% (-0.1%) vs cost Δ% (-32.2%) disagree by 32.0pp (>5pp) — likely metering/counting, not harness
- task add-feature: tok Δ%=+0.0% cost Δ%=-54.6% (disagree 54.6pp); fail n 5→5
- task build-a-cli: tok Δ%=-0.9% cost Δ%=-56.1% (disagree 55.2pp); fail n 5→5
- task make-ci-green: tok Δ%=-0.0% cost Δ%=-32.9% (disagree 32.9pp); fail n 5→5
- task taskflow: tok Δ%=-0.0% cost Δ%=-31.1% (disagree 31.1pp); fail n 5→5
- $/cell fail mix: without n_fail=40 fail_cost_mean=$0.0402 (40 costed); with n_fail=40 fail_cost_mean=$0.0273 (40 costed). Check whether $/cell includes failed/retry cells differently after vs before.
### PR 3115
- PR-aggregate token Δ% (+0.1%) vs cost Δ% (-8.9%) disagree by 8.9pp (>5pp) — likely metering/counting, not harness
- task build-a-cli: tok Δ%=+0.3% cost Δ%=-27.9% (disagree 28.2pp); fail n 5→5
- task misleading-error: tok Δ%=+0.1% cost Δ%=-29.8% (disagree 29.9pp); fail n 5→5
- $/cell fail mix: without n_fail=40 fail_cost_mean=$0.0456 (40 costed); with n_fail=40 fail_cost_mean=$0.0415 (40 costed). Check whether $/cell includes failed/retry cells differently after vs before.

## Quarantine

Pre-hard5 3-trial cells copied to `results/ab-quarantine/pre-hard5-<pr>/` before wipe+5-trial rerun.

Spend: cumulative est. **$529.66** (prior $432.34; hard5 phase +$97.32).

## Exercised check: scored rows


Appended by ENOENT monitor 2026-10-05 18:01 ET. Read-only over existing `results/ab/{13331,26821,23771}` cells + opencode worktree diffs. Nothing paid.

### #13331 — webfetch image attachments (`tool/webfetch.ts`)

- **Change (with=`ba54cee55e…`, without parent=`847e06f9e1…`):** when HTTP `content-type` is image (non-SVG), return `Image fetched successfully` + base64 `data:` file attachment instead of decoding as text.
- **Evidence:** grep of all 80 cell `output_tail` under `results/ab/13331/cells/{without,with}/` for `webfetch|Image fetched successfully|data:image` → **0 hits** either side. Classes mostly `solved` (36/40) + rate_limited/timeout; tasks are local coding fixtures unlikely to call webfetch.
- **Label:** **not exercised** (0/40 without, 0/40 with). Cannot attribute A/B deltas to the image-attachment branch.

### #26821 — reduce shell/todowrite/task prompts (`tool/shell/shell.txt`, `todowrite.txt`, `task.txt`)

- **Change (with=`548648a3d9…`, without=`4643e13170…`):** heavy prompt-token cut (~302→84 lines across the three tool description files). Always present in the tool-definition surface when those tools are registered; invocation proves the tool (and its description) was in play.
- **Evidence (`output_tail` tool markers):**
  - `bash`/`shell`: **34/40 without**, **29/40 with** exercised (e.g. `results/ab/26821/cells/without/make-it-run/3.json`, `…/with/make-it-run/3.json`).
  - `todowrite`/`todo`: **0/40** either side — **not exercised**.
  - `task`: **0/40** either side — **not exercised**.
- **Label:** **partially exercised** — shell prompt path yes; todowrite/task prompt paths no. Pass 40/40 both sides.

### #23771 — LSP pull diagnostics (`lsp/client.ts`, `tool/edit.ts` / `write.ts`)

- **Change (with=`e383df4b17…`, without=`58db41b4b9…`):** add `textDocument/diagnostic` + `workspace/diagnostic` pull support; edit/write switch `lsp.touchFile(file, true)` → `lsp.touchFile(file, "document")` then `lsp.diagnostics()`.
- **Evidence:** no literal `textDocument/diagnostic` strings in truncated `output_tail`s (expected — wire protocol not echoed). Proxy for path: cells whose tail shows `[tool: edit|write|apply_patch]` (those call `touchFile`→`diagnostics`).
  - without (old `touchFile(…, true)`): **23/40** with edit/write (e.g. `results/ab/23771/cells/without/make-it-run/3.json`).
  - with (new `touchFile(…, "document")` + pull client): **22/40** (e.g. `results/ab/23771/cells/with/make-it-run/3.json`).
- **Label:** **exercised** on the with-side pull path in **22/40** cells; without exercises only the pre-PR touchFile(true) path (**23/40**). Remaining cells had no edit/write in the visible tail → **not exercised** for this PR’s code path. Whether the language server actually returned pull diagnostics is **undeterminable** from cell artifacts (no LSP wire logs retained).

### Source roots
- `results/opencode-src/worktrees/<sha>/packages/opencode/src/{tool,lsp}/`
- Cells: `results/ab/{13331,26821,23771}/cells/`


---

## Re-score: truncated cells as infra (2026-10-05)

Free read-only re-score of on-disk cells. Script: `results/ab-logs/rescore_truncated.py`. No `run_ab`, no cell deletes/moves, no paid calls.

### Classifier rule

A cell is classed **infra** (excluded from wall / output / uncached-input / billable-tok / $/cell means) when any of:

1. `failure_class ∈ {infra, rate_limited, stalled, timeout}`
2. Unsuccessful cell text (`error` / `failure_reason` / `checker_stderr` / `checker_stdout` / `output_tail`) matches rate-limit markers: `429`, `overloaded`, `RESOURCE_EXHAUSTED`, `rate_limit` / `rate limit` / `ratelimit`
3. Unsuccessful or `completed=False` cell text matches timeout markers: `timeout after`, `harness timeout`, `killed`, `deadline` / `DeadlineExceeded`
4. Short-wall (<8s) unsuccessful exit-N / `Unhandled chunk` death with `tokens_output ≤ 32` (legacy ~5s infra shape; does **not** promote `failure_class=incompatible`)

Pass-rate: **(a)** excluding infra cells, **(b)** raw `success/n`. Asymmetric exclusion flag when `|n_infra_wo − n_infra_wi| ≥ 2` or `>10%` of n (surviving means not comparable). Noise floor reference (first-pass A/A, modern rows): ±12% wall / ±19% billable tok / ±11% cost — mark outside/inside only, no CLEAR claims.

### Validation — #13331 webcore (brief)

| cell | failure_class | out | error | infra? |
|---|---|---|---|---|
| without/1 | solved | 41511 | — | kept |
| without/2–5 | rate_limited | 39945…33475 | timeout after 840s | **infra** (fc=rate_limited) |
| with/1–3 | rate_limited | 4580, 809, 643 | timeout after 840s | **infra** (fc=rate_limited) |
| with/4 | timeout | 158 | timeout after 840s | **infra** (fc=timeout) |
| with/5 | solved | 67118 | — | kept |

Matches the brief: with-side truncated outs 158–4.6k excluded; without-side rate_limited (still ~33–41k out) also excluded under the locked rule.

### Compact table (Δ% as old→new after exclusion)

| PR | n kept/infra (wo→wi) | Pass excl (raw) | Wall Δ% old→new | Out Δ% old→new | Unc-in Δ% old→new | Tok/cell Δ% old→new | $/cell Δ% old→new | |tok−$| | Floor (wall/tok/$) | Flags |
|---|---|---|---|---|---|---|---|---|---|---|
| 13331 | 36/4→36/4 | 1.000→1.000 (0.900→0.900) | +5.5%→+19.3% | -45.1%→+21.7% | -10.6%→-0.8% | -17.4%→+2.8% | -14.2%→+6.1% | 3.3 | OUTSIDE/inside/inside | — |
| 23771 | 40/0→40/0 | 1.000→1.000 (1.000→1.000) | +17.9%→+17.9% | +21.0%→+21.0% | +3.2%→+3.2% | +7.3%→+7.3% | +7.5%→+7.5% | 0.1 | OUTSIDE/inside/inside | — |
| 26821 | 40/0→40/0 | 1.000→1.000 (1.000→1.000) | +9.5%→+9.5% | +14.7%→+14.7% | +13.0%→+13.0% | +7.8%→+7.8% | -15.1%→-15.1% | 22.9 | inside/inside/OUTSIDE | TOK$=22.9pp |
| 4838 | 24/0→24/0 | 1.000→1.000 (1.000→1.000) | +4.5%→+4.5% | +5.2%→+5.2% | +7.6%→+7.6% | +21.6%→+21.6% | -1.7%→-1.7% | 23.3 | inside/OUTSIDE/inside | TOK$=23.3pp |
| 5066 | 24/0→24/0 | 1.000→1.000 (1.000→1.000) | -7.7%→-7.7% | -5.2%→-5.2% | -2.1%→-2.1% | -9.6%→-9.6% | -12.6%→-12.6% | 2.9 | inside/inside/OUTSIDE | — |
| 5131 | 24/0→24/0 | 1.000→1.000 (1.000→1.000) | +4.3%→+4.3% | +4.9%→+4.9% | +6.9%→+6.9% | +16.4%→+16.4% | -4.4%→-4.4% | 20.7 | inside/inside/inside | TOK$=20.7pp |
| 5140 | 24/0→24/0 | 1.000→1.000 (1.000→1.000) | +3.4%→+3.4% | +2.4%→+2.4% | +5.4%→+5.4% | +10.4%→+10.4% | +54.8%→+54.8% | 44.4 | inside/inside/OUTSIDE | TOK$=44.4pp |
| 5527 | 24/0→24/0 | 1.000→1.000 (1.000→1.000) | +1.1%→+1.1% | -3.7%→-3.7% | -4.5%→-4.5% | -9.6%→-9.6% | -1.3%→-1.3% | 8.4 | inside/inside/inside | TOK$=8.4pp |
| 6524 | 24/0→24/0 | 1.000→1.000 (1.000→1.000) | -11.8%→-11.8% | -8.3%→-8.3% | -6.9%→-6.9% | -17.0%→-17.0% | -3.3%→-3.3% | 13.7 | inside/inside/inside | TOK$=13.7pp |

Primary-metric floor marks use **new** (excl-infra) Δ%: wall / billable-tok / $. ENOENT rows marked for reference only (floor defined on first-pass modern hard5).

### Cells reclassified per row/side

| PR | without infra | with infra | ASYM? | notes |
|---|---|---|---|---|
| 13331 | 4 (rate_limited×4) | 4 (rate_limited×3, timeout×1) | no (4=4) | all webcore; windows overlap 16:01–16:21 ET |
| 23771 | 0 | 0 | no | unchanged |
| 26821 | 0 | 0 | no | unchanged; tok/$ DISAGREE 22.9pp |
| 4838 | 0 | 0 | no | unchanged |
| 5066 | 0 | 0 | no | unchanged |
| 5131 | 0 | 0 | no | unchanged |
| 5140 | 0 | 0 | no | unchanged |
| 5527 | 0 | 0 | no | unchanged |
| 6524 | 0 | 0 | no | unchanged |
| 4204 (off sheet) | 22 infra + 2 incompatible | 22 infra + 2 incompatible | — | list only; ~5s deaths |

### #13331 per-task output Δ% after exclusion

| task | n_wo/n_wi (infra wo/wi) | out wo→wi | out Δ% |
|---|---|---|---|
| add-feature | 5/5 (0/0) | 5535→5100 | −7.9% |
| build-a-cli | 5/5 (0/0) | 1845→1843 | −0.1% |
| fix-failing-test | 5/5 (0/0) | 714→713 | −0.1% |
| make-ci-green | 5/5 (0/0) | 1273→1300 | +2.2% |
| make-it-run | 5/5 (0/0) | 783→765 | −2.2% |
| misleading-error | 5/5 (0/0) | 1044→1009 | −3.3% |
| taskflow | 5/5 (0/0) | 2294→2365 | +3.1% |
| **webcore** | **1/1 (4/4)** | **41511→67118** | **+61.7%** |

Aggregate output Δ flips **−45.1% → +21.7%** once truncated webcore cells are dropped; the surviving webcore pair is n=1 per side (high variance). Non-webcore tasks stay within a few percent.

### Time clustering of excluded cells

- **#13331 webcore:** without trials 2–5 start≈16:01:09–16:01:26 ET, end≈16:15; with trials 1–4 start≈16:06:37–16:07:53 ET, end≈16:20–16:21. **Windows overlap across sides** (~16:06–16:15 ET) — consistent with a shared rate-limit/timeout burst, not a build-only effect.
- **#4204:** all 44 `failure_class=infra` cells cluster in the 17:00 ET hour (separate ENOENT-driver wave); incompatible×2/side not counted as infra.
- No other scored PR had infra exclusions, so no further cross-PR overlap among hard5/ENOENT sheet rows.

### Floor marks after re-score (new Δ%, primary)

| PR | wall | billable tok | cost | notes |
|---|---|---|---|---|
| 13331 | **OUTSIDE** (+19.3%) | inside (+2.8%) | inside (+6.1%) | output primary +21.7% also >±19% band if applied to out; old −45% was truncation artifact |
| 23771 | **OUTSIDE** (+17.9%) | inside (+7.3%) | inside (+7.5%) | unchanged |
| 26821 | inside (+9.5%) | inside (+7.8%) | **OUTSIDE** (−15.1%) | unchanged; |tok−$|=22.9pp |
| 4838 | inside | **OUTSIDE** (+21.6% tok) | inside | ref only |
| 5066 | inside | inside | **OUTSIDE** (−12.6%) | ref only |
| 5131 | inside | inside | inside | ref only; |tok−$|=20.7pp |
| 5140 | inside | inside | **OUTSIDE** (+54.8%) | ref only; |tok−$|=44.4pp |
| 5527 | inside | inside | inside | ref only; |tok−$|=8.4pp |
| 6524 | inside | inside | inside | ref only; |tok−$|=13.7pp |

### Surprises

1. **#13331 headline flips:** excluding 4+4 webcore truncations turns output −45.1% into **+21.7%** and billable tok −17.4% into **+2.8%** (inside tok floor); wall moves the other way to **+19.3% OUTSIDE** floor.
2. Without-side rate_limited webcore cells still had **high** output (~33–41k) but are dropped under the locked rule — so the old −45% was not only “with truncated low”, it was also “without kept high failures in the mean”.
3. Exclusion is **symmetric** on #13331 (4=4); surviving means are formally balanced but webcore rests on **n=1** solved cell per side.
4. ENOENT sheet rows (4838…6524) have **zero** truncation infra — re-score equals old numbers.



## Reclassified ~5s cells as infra (2026-10-05, rule 4b)

Rule 4b (PM-requested 2026-10-05): failed cell, wall <8s, "Unhandled chunk type" in output, any output token count (83–820 tokens are pre-crash partial output), plus existing rate-limit/timeout rules. Read-only over results/ab/<pr>/cells/ (2334/3115 dirs combine hard5 + setaside2 cells). Reproduce: `rescore_truncated.py --rule-4b` (default off; locked rule unchanged).

| PR | side | total | infra | kept | pass among kept | status |
|---|---|---|---|---|---|---|
| 2334 | without | 40 | 38 | 2 | 0/2 | off sheet: 2 kept cell(s) too few to score (pending R1–R4) |
| 2334 | with | 40 | 39 | 1 | 0/1 | off sheet: 1 kept cell(s) too few to score (pending R1–R4) |
| 2367 | without | 24 | 24 | 0 | 0/0 | off sheet: all infra (pending runner fixes R1–R4) |
| 2367 | with | 24 | 23 | 1 | 0/1 | off sheet: 1 kept cell(s) too few to score (pending R1–R4) |
| 3052 | without | 24 | 24 | 0 | 0/0 | off sheet: all infra (pending runner fixes R1–R4) |
| 3052 | with | 24 | 24 | 0 | 0/0 | off sheet: all infra (pending runner fixes R1–R4) |
| 3115 | without | 40 | 38 | 2 | 0/2 | off sheet: 2 kept cell(s) too few to score (pending R1–R4) |
| 3115 | with | 40 | 38 | 2 | 0/2 | off sheet: 2 kept cell(s) too few to score (pending R1–R4) |

The remaining 1–2 kept cells per side (8–10s walls, all failed) are too few to score, so **2334, 2367, 3052, 3115 are all off the sheet pending runner fixes R1–R4**. Earlier sections above are left as originally reported.
