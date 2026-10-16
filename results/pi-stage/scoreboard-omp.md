# Oh My Pi scoreboard (rebuilt 2026-10-16)

Source: openbench main c8372a5 (#29), results/omp-screen5, omp-screen5-b2, omp-cap30-16, omp-cap30-b2, omp-aa28-apikey.
Opus 5.5 via the vertex-anthropic proxy. Built by scratch/build_scoreboard_omp.py; no model calls.

**Rules**
- 5- and 10-run rows are **screening only**. They are not effects. A row becomes an effect only at 30/side.
- **$ is never an effect.** Per-cell cost moves with cache luck (AA: +39% between identical builds); it is reported, never tested.
- **AA2 band:** a screen delta inside the AA2 (row 28 parent vs itself, auth apiKey) 95% interval is noise. Rows 28+ are judged against AA2; earlier rows against AA.
- Pass rate = solved / scored. Infra cells are excluded and shown separately. Timeouts count as fails. Warm-up cells (abba runs) are excluded. Infra reruns are folded in, per side, up to that side's infra count.
- Deltas are merge vs parent relative to the parent mean, with 95% bootstrap intervals (10,000 resamples per side, seed 0).

**Restore note (2026-10-16):** the box was restored to a 2026-10-07 snapshot about 06:41 ET. The original scoreboard-omp.csv/.md, omp-triage.csv, the trigger notes and 6 unmerged fixtures were lost; none were on GitHub. This file was rebuilt from the per-cell JSONs on main. The verdicts come from the PM's list and results/ab-logs. Row 36's numbers come from the room report because its cells were never pushed. The 6 fixtures (cutover, finddir, dirread, findext, mdtable, tailread) were re-authored, not recovered.


| Row | Task | n (P/M) | Infra (P/M) | Pass P | Pass M | Req#1 Δ | Total tokens Δ [95% CI] | Requests Δ | Output Δ | Cost Δ (not an effect) | Ledger $ | Status | Note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| AA (row 16 parent) | trig-omp-multistep | 4/4 | 0/0 | 4/4 (1.000) | 4/4 (1.000) | -1 | +3.6% [-6.0, +16.3] | +3.0% [-5.9, +15.2] | +5.8% [-11.1, +25.1] | +38.5% [+12.6, +64.2] | 1.60 | A/A | abba 6/side, warm-up excluded |
| AA2 (row 28 parent, auth apiKey) | trig-omp-fanout | 4/4 | 0/0 | 4/4 (1.000) | 4/4 (1.000) | +0 | -2.9% [-11.4, +6.4] | -2.8% [-10.8, +6.1] | -4.2% [-20.7, +14.6] | +15.6% [+5.7, +22.7] | 7.14 | A/A | band used for 28 and later rows |
| AA38 (row 38 parent) | trig-omp-bugfix-regress | 4/4 | 0/0 | 3/4 (0.750) | 3/4 (0.750) | -0 | -16.8% [-66.3, +46.8] | -16.1% [-65.6, +45.8] | -24.2% [-74.7, +76.3] | -16.7% [-84.9, +264.6] | 2.56 | A/A |  |
| AA44 (row 44 parent) | trig-omp-multistep | 4/4 | 0/0 | 4/4 (1.000) | 4/4 (1.000) | -1 | -1.5% [-21.7, +25.9] | +0.0% [-18.8, +25.0] | -6.5% [-29.4, +19.8] | -22.2% [-58.0, +45.6] | 0.96 | A/A |  |
| AA19 (row 19 parent, thinking off) | trig-omp-multistep | 4/4 | 0/0 | 4/4 (1.000) | 4/4 (1.000) | +2 | -0.7% [-31.9, +50.0] | +0.0% [-30.0, +47.1] | -3.6% [-19.0, +11.1] | -31.7% [-62.4, +32.1] | 1.49 | A/A | thinking off |
| 16 @30 | trig-omp-multistep | 30/30 | 0/0 | 30/30 (1.000) | 29/30 (0.967) | +10418 | +54.7% [+44.4, +63.9] | +3.4% [-3.3, +9.4] | -1.2% [-10.2, +7.2] | +131.6% [+103.3, +161.2] | 20.04 | CONFIRMED (efficiency) | +10,418 first-request tokens; total +54.7%; pass unchanged |
| 16 screen | trig-omp-multistep | 5/5 | 0/0 | 5/5 (1.000) | 5/5 (1.000) | +10416 | +35.3% [+25.6, +46.4] | -9.1% [-14.9, -2.4] | -4.6% [-15.8, +8.3] | +72.3% [+45.8, +110.2] | 3.72 | screen |  |
| 38 @30 | trig-omp-bugfix-regress | 30/30 | 0/0 | 28/30 (0.933) | 28/30 (0.933) | +354 | +3.5% [-4.0, +13.8] | +2.3% [-4.9, +12.2] | +1.4% [-7.2, +13.1] | +12.5% [-4.0, +34.2] | 9.56 | CONFIRMED (behavioural) | bash git stash 27/30 merge vs 0/30 parent, Fisher p=9.2e-14; regression test kept 30/30 vs 27/30, p=0.24; tokens inside band |
| 38 screen | trig-omp-bugfix-regress | 5/5 | 0/0 | 5/5 (1.000) | 5/5 (1.000) | +356 | +11.9% [-1.4, +27.6] | +10.0% [-2.3, +25.0] | +15.2% [-1.0, +34.4] | +21.0% [-22.0, +74.5] | 3.41 | screen | tokens +11.9% borderline signal -> 30/side |
| 19 @30 (thinking off) | trig-omp-multistep | 30/30 | 0/0 | 26/30 (0.867) | 27/30 (0.900) | -111 | +3.2% [-11.6, +21.0] | +4.3% [-9.9, +21.1] | +5.7% [-7.6, +21.7] | +6.3% [-8.8, +25.4] | 8.84 | NULL @30/side (screened-null) | all trials; 7 timeouts in trials 16-21 (suspected shared stall) |
| 19 @30 excl. trials 16-21 | trig-omp-multistep | 24/24 | 0/0 | 24/24 (1.000) | 24/24 (1.000) | -111 | +0.1% [-13.0, +15.1] | +1.4% [-11.0, +15.4] | +2.2% [-6.3, +11.6] | +5.9% [-7.7, +22.7] | 8.84 | NULL @30/side (screened-null) | shared stall trials 16-21 excluded both sides (24/side) |
| 19 screen (thinking off) | trig-omp-multistep | 5/5 | 0/0 | 5/5 (1.000) | 5/5 (1.000) | -111 | +26.8% [+3.0, +60.4] | +25.0% [+3.6, +55.0] | +17.3% [-3.2, +44.7] | +13.8% [-12.0, +61.9] | 2.04 | screen | 5-run +27% tokens; did not hold |
| 44 @30 | trig-omp-multistep | 30/30 | 0/0 | 27/30 (0.900) | 29/30 (0.967) | -142 | +3.3% [-5.4, +13.4] | +3.7% [-4.6, +13.4] | +7.5% [-4.7, +21.6] | +5.8% [-15.8, +32.8] | 5.97 | NULL @30/side (screened-null) | 2+2 infra rerun once, all solved |
| 44 screen (rerun) | trig-omp-multistep | 5/5 | 0/0 | 5/5 (1.000) | 5/5 (1.000) | -141 | -13.8% [-29.3, +4.3] | -13.2% [-27.5, +5.6] | -0.6% [-20.9, +21.3] | +5.9% [-26.3, +51.1] | 1.48 | screen | 5-run -14% tokens; did not hold. First attempt (omp-44) 4 infra + 2 timeouts |
| 15 / #13 screen | trig-omp-multistep | 5/5 | 0/0 | 5/5 (1.000) | 5/5 (1.000) | -18 | +0.8% [-0.3, +1.8] | +0.0% [+0.0, +0.0] | -9.6% [-20.2, +2.6] | +6.2% [-18.1, +37.3] | 2.61 | SCREENED-NULL |  |
| 21 screen | trig-omp-unusedparam | 5/5 | 0/0 | 5/5 (1.000) | 5/5 (1.000) | +322 | +13.0% [+1.1, +27.0] | +11.4% [+0.0, +25.0] | +9.0% [+6.5, +11.6] | +12.2% [-16.3, +55.5] | 4.37 | EXERCISED-NULL | rule reached model (+322 req#1); deleted 5/5 both sides (parent at ceiling) |
| 28 screen | trig-omp-fanout | 5/5 | 0/0 | 5/5 (1.000) | 5/5 (1.000) | +396 | -9.5% [-17.0, +0.0] | -10.9% [-18.0, -2.3] | +6.4% [-6.5, +23.7] | +4.0% [-15.8, +24.7] | 9.23 | SCREENED-NULL (borderline) | requests -10.9% vs AA2 band lower edge -10.8%; zero task calls both sides |
| 33 screen | trig-omp-multistep | 5/5 | 0/0 | 5/5 (1.000) | 5/5 (1.000) | +198 | +3.7% [-5.5, +14.0] | +3.0% [-5.7, +12.9] | +1.0% [-11.3, +14.7] | +5.2% [-16.4, +34.8] | 7.31 | SCREENED-NULL |  |
| 35 screen | trig-omp-multistep | 4/4 | 0/0 | 4/4 (1.000) | 4/4 (1.000) | +28 | -3.2% [-14.4, +12.9] | -3.7% [-14.3, +12.0] | +7.3% [-6.3, +23.0] | +19.0% [+2.8, +43.6] | 4.62 | SCREENED-NULL | abba 6/side, warm-up excluded |
| 43 screen | trig-omp-image | 5/5 | 0/0 | 5/5 (1.000) | 5/5 (1.000) | -152 | -0.5% [-0.5, -0.5] | +0.0% [+0.0, +0.0] | -3.9% [-7.7, -0.4] | +21.8% [-24.8, +157.0] | 2.94 | SCREENED-NULL |  |
| 39 screen | trig-omp-image | 5/5 | 0/0 | 5/5 (1.000) | 5/5 (1.000) | +60 | +0.2% [+0.2, +0.2] | +0.0% [+0.0, +0.0] | +0.4% [-4.5, +6.0] | -12.7% [-44.6, +70.6] | 2.04 | SCREENED-NULL |  |
| 30 screen (thinking off) | trig-omp-netclient | 5/5 | 0/0 | 5/5 (1.000) | 5/5 (1.000) | -104 | -10.5% [-16.9, -0.6] | -10.3% [-16.7, +0.0] | -9.7% [-18.7, -3.0] | +7.5% [-9.5, +39.6] | 7.63 | SCREENED-NULL (thinking off) | thinking-on attempt: 10/10 infra (invalid thinking signature) |
| 31 screen (thinking off) | trig-omp-callsites | 4/3 | 1/2 | 4/4 (1.000) | 3/3 (1.000) | -144 | +3.9% [-11.8, +28.1] | +2.6% [-11.1, +23.1] | -3.6% [-11.3, +4.7] | +10.0% [-13.4, +43.2] | 7.77 | SCREENED-NULL (thinking off) | 3 infra (tool_choice 400); thinking-on attempt 10/10 infra |
| 32 screen (thinking off) | trig-omp-experiment | 5/5 | 0/0 | 5/5 (1.000) | 5/5 (1.000) | +259 | +0.7% [+0.5, +0.8] | +0.0% [+0.0, +0.0] | -1.6% [-9.3, +7.0] | -21.2% [-37.1, +1.0] | 5.80 | SCREENED-NULL (thinking off) | thinking-on attempt 7/10 infra |
| 36 screen | trig-omp-reported |  |  |  |  |  |  |  |  |  |  | SCREENED-NULL (data lost) | No cells on main. From Thesis Developer's room report 2026-10-13: 10/10 solved, tokens +0.2% [-6.5,+7.5], requests 0.0%, detector 0/5 vs 0/5, $8.61. Rerun pending. (First attempt on main: 10/10 infra, ClaudeV5 natives crash.) |
| 20 | trig-omp-multiedit |  |  |  |  |  |  |  |  |  |  | NOT EXERCISABLE | 13.7.4 build ignores adaptive thinking pin; both sides 400 (10/10 infra on main) |
| 22 |  |  |  |  |  |  |  |  |  |  |  | NOT EXERCISABLE (skipped) | bash timeout-clamp notice; no unforced trigger |
| 45 |  |  |  |  |  |  |  |  |  |  |  | NOT EXERCISABLE (skipped) | mid-stream stall recovery; provider-fault only |
| 37 | trig-omp-cutover |  |  |  |  |  |  |  |  |  |  | AWAITING SCREEN | queue order per PM |
| 18 | trig-omp-callsites |  |  |  |  |  |  |  |  |  |  | AWAITING SCREEN | queue order per PM |
| 29 | trig-omp-callsites |  |  |  |  |  |  |  |  |  |  | AWAITING SCREEN | queue order per PM |
| 26 |  |  |  |  |  |  |  |  |  |  |  | AWAITING SCREEN | queue order per PM |
| 41 | trig-omp-multistep |  |  |  |  |  |  |  |  |  |  | AWAITING SCREEN | queue order per PM |
| 25 | trig-omp-finddir |  |  |  |  |  |  |  |  |  |  | AWAITING SCREEN | queue order per PM |
| 42 | trig-omp-multistep |  |  |  |  |  |  |  |  |  |  | AWAITING SCREEN | queue order per PM |
| 17 |  |  |  |  |  |  |  |  |  |  |  | AWAITING SCREEN | queue order per PM |
| 40 | trig-omp-dirread |  |  |  |  |  |  |  |  |  |  | AWAITING SCREEN | queue order per PM |
| 14 | trig-omp-findext |  |  |  |  |  |  |  |  |  |  | AWAITING SCREEN | queue order per PM |
| 23 | trig-omp-tailread |  |  |  |  |  |  |  |  |  |  | AWAITING SCREEN | queue order per PM |
| 27 | trig-omp-callsites |  |  |  |  |  |  |  |  |  |  | AWAITING SCREEN | queue order per PM |
| 24 | trig-omp-mdtable |  |  |  |  |  |  |  |  |  |  | AWAITING SCREEN | queue order per PM |
| 34 | trig-omp-callsites |  |  |  |  |  |  |  |  |  |  | AWAITING SCREEN | queue order per PM |
