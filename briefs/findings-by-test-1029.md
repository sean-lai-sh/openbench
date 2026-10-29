# Findings by test (2026-10-29)

Thesis Researcher brief for Sean Lai's senior thesis, repo `sean-lai-sh/openbench`. It was written read-only, with nothing committed. Every number comes from committed repo data, from the briefs in `/workspace/thesis-research/briefs/` (cited for each section), or from today's room rulings and Developer reports. "Not yet computed" means no figure exists yet.

Effect rule used throughout: there is a token effect only when the 95% bootstrap CI on the with/without ratio excludes 0 **and** the point estimate sits outside the model's A/A noise band. The bands are Sonnet −6.5% to +6.8% and Opus −10.4% to +4.4%. Pass-rate tests use Fisher two-sided.

## Stage 1 and A/A: main OpenCode A/B on easy tasks
- **Question:** do small OpenCode harness PRs change tokens, pass rate or behaviour on the OpenBench easy tasks?
- **Setup:** each PR's parent build ("without") is compared against its merge build ("with"), 30 trials per side, on Sonnet and Opus. A/A runs set the noise bands.
- **n:** 31 PRs per model at 30 per side.
- **Headline:** several PRs cut tokens with no change in pass rate. #3052 is about −65% on Sonnet and −52% on Opus. #13331 and #26821 are about −25% to −28%. #913 on Opus is +23.4%. Opus-only candidates are #13090 at −16.9% [−26.6, −7.0], #5140 at −13.6% [−21.3, −4.5] and #4204 trig-subagent-resume at +25.0% [+16.0, +33.5]. No efficiency PR moved pass rate.
- **Behaviour:** on #25226 (Sonnet), the temp dir leaked in 10/30 trials without the change and 0/30 with it (p ≈ 0.0008). The D1 split ([#114](https://github.com/sean-lai-sh/openbench/pull/114)) shows that the prompt-only change stops leaks, 7/30 → 0/30, but cuts solves from 29/30 to 21/30 (p = 0.012).
- **Caveats:** the tasks are at ceiling, so pass rate can't move. Each result comes from a single run, and the Opus-only flags are candidates, not findings.
- **Spend:** about $1,085 for OpenCode plus about $165 for Oh My Pi. A/A cost $28.27 on Sonnet, $29.12 for Opus OpenCode and $33.36 for Opus Oh My Pi.
- **Status:** final as an easy-suite result.
- **Sources:** `token-efficiency-original-study-2026-10-24.md`, `sedoc-interim-2026-10-23.md`.

## F01 and F02: full Sonnet run, step 8, first batches
- **Question:** same as Stage 1, across every runnable PR (413 total, 351 runnable).
- **Setup:** Sonnet only, 30 per side, run on the shared bot computer.
- **n:** 56 PRs scored. That is the 9-PR pilot (#107), F01, F02 and part of F03.
- **Headline:** no pass-rate effects. Four modest token effects: #795 +18.3% [+2.0, +37.3], #1109 −6.9% [−11.9, −1.7], #1443 +11.3% [+2.0, +22.8] and #2051 −7.5% [−12.9, −1.9]. Two of the other 52 PRs fall inside the noise band.
- **Caveats:** a disk-space guard kept stopping the runner, so #950 and #3185 were left unscored and are rerun on the VM. Results are not yet split out by F01 versus F02.
- **Status:** final for these 56 PRs.

## F03-2: remainder batch on the VM
- **Question:** same as F01 and F02, continued on `thesis-h1-cpu`.
- **Setup:** scored from main at `41877c92`, 30 per side.
- **n:** 11 PRs.
- **Headline:** 10 PRs scored 30/30 on both sides. PR 3424 scored 0/30 on both sides. The pass-rate difference is 0 on every PR, with CI ±0.114.
- **Caveats:** PR 3424's 0/30 is most likely a checker defect. It was not affected by the docker issue, so it stands as scored. The task pack is too easy to show any pass-rate effect, which is why F04 and Stage 4 need harder tasks.
- **Spend:** $58.61.
- **Status:** final. Token-effect results for F03-2 are not yet computed in my notes.

## H1: hard-suite probe
- **Question:** are the 9 pre-registered hard tasks in a useful difficulty band?
- **Setup:** probe in [#119](https://github.com/sean-lai-sh/openbench/pull/119), Sonnet and Opus.
- **n:** 18 scored Sonnet cells and 16 scored Opus cells.
- **Headline:** Sonnet solved 9/18 and Opus 9/16, so about 50%. Nearly every fail was a wrong answer. No cell hit the 2400 s cap or a token limit, and there was one Opus hang. Some tasks sit at the floor (sam, polyglot, dna-insert) and some at the ceiling (filter-js, model-extraction, torch-tensor).
- **Spend:** about $12 of model cost, plus the VM.
- **Status:** final as a calibration result. It is not an effect test.

## H2: hard suite, first batch plus deferred rows
- **Question:** do the token savings hold, and does pass rate move, when tasks are hard?
- **Setup:** pre-registration v2 + A1 + A2 (sha256 `a8668fc6…`). The design is 15 rows × 9 tasks × 10 per side, 2,700 cells. Deferred rows: [#130](https://github.com/sean-lai-sh/openbench/pull/130), runner `e2ac6b75`, seed 1022.
- **First batch, 7 rows:** no significant pass-rate effect. The largest was Sonnet 3052 at +12 pp (p = 0.12). No row-level token effect, and the CIs are wide.
- **Deferred rows, task level:**
  - Sonnet 13331 shows no effect.
  - Sonnet 26821 shows a **persistent** token effect on 5 of 9 tasks, from −19.1% to −28.6%. Examples: dna-insert −21.9% [−29.7, −12.9] and video-processing −24.9% [−39.1, −6.4].
  - Opus 4204 shows no effect.
  - Opus 5140 and Opus 13090 each have a single-task effect on model-extraction: +111.1% and −49.9%.
  - Opus 13331 shows mixed signs: model-extraction +52.2% and regex-chess −26.5%.
  - No per-task Fisher test reached p ≤ 0.05. The lowest was p = 0.070.
- **Caveats:**
  - A control lights up on four tasks, so per-task results stay exploratory until a multiple-comparison rule is pre-registered.
  - Opus 26821 has only 32/32 cells and Sonnet 11731 has 90/0, so both are set aside as incomplete.
  - 3 image_payload rows are excluded.
  - Two kinds of failure are scored as agent fails, not environment problems:
    - 2400 s kills. The reference solutions run in 13.0 s and 42.4 s.
    - The 52 watchdog hangs and the 6 idle-timer cells. All had their last streamed update between 297.1 s and 300.8 s before the kill, so they were real silences of about 300 s. Under the 290 s cutoff, none was relabeled.
- **Status by part:**
  - **Quarantined, rerun pending:** H2 795 and 913, all three arms including Opus 913 (runner `980e71b6`, `pre_fix_runner`).
  - **Quarantined, full-pair reruns pending #192:** 3052 on both models, after Sonnet's ledger showed 3 signature 400s on the with side, and 5140 filter-js. Both hit thinking-signature 400s.
  - **Rerun pending #191:** the 32-cell checker-timeout set.
  - The other deferred rows above are scored, but those scores are from before the reruns.
- **Rerun plan:** 1,112 cells, $280.53, $300 stop. It starts after the Pi vs OpenCode batch.
- **Sources:** `h2-deferred-scores-2026-10-24.md`, `sedoc-interim-2026-10-23.md`, today's room.

## 26821 (Sonnet, hard suite)
- **Headline:** this is the only row where the easy-suite token saving (about −25% to −28%) reproduces on hard tasks. It shows effects on 5 of 9 tasks. Pass rate went 24/90 → 32/90, and the pooled Fisher test is p = 0.26, not significant. Pooled tokens are −13.7% [−31.6, +7.7], which is not the primary measure. Model cost was $44.69.
- **Caveats:** Opus 26821 is incomplete because it hit the $500 batch stop. One SDK-drift infra cell and two model-extraction idle cells are in the rerun or agent-fail sets described above.
- **Status:** Sonnet is scored. Opus is set aside.

## Harness smoke tests and gates
- **Pi gate cell:** $0.040017, scored 0.
- **OpenCode gate cell:** $0.157324, scored 0.
  - Both left binaries in `/app/polyglot`.
  - The first OpenCode Sonnet gate is marked `off_protocol` and is excluded from scoring.
- **OpenCode Sonnet gate on `61ca90d0` (#189):** passed model-match.
  - All 4 proxy requests asked for Sonnet 5.5 and were served Sonnet 5.5, with `off_protocol=false`.
  - `small_model_deviation=true` is recorded.
  - It produced 3,943 output tokens, so it was not a startup exit.
  - The task itself failed as a wrong answer, and the cell cost $0.12.
  - The data is in #190. #189 merged as `09b2e813` and #190 as `e507e38c`.
- **Status:** final. These are protocol checks, not findings.

## Pi vs OpenCode
- **Question:** what difference does the harness make, with the model held fixed?
- **Setup:** 180 cells from `e507e38c`. Bridge mode, each harness on its default thinking setting, `drop_block` off and `--require-model-match` on. $50 stop on proxy cost. Results go to `results/pi-vs-oc-180-1029/`.
- **n, headline, CI:** not yet computed.
- **Status:** running.

## What we can claim now vs not yet
**Can claim now:**
- On easy tasks, harness PRs can change token use a lot without changing pass rate. Examples are #3052, #13331, #26821 and Opus #913.
- One clean behaviour interaction: #25226's prompt-only change stops temp-dir leaks but cuts solves.
- Across the 67 step-8 PRs scored so far (56 plus F03-2's 11), no harness PR changed easy-task pass rate. The easy pack is at ceiling, which is why harder tasks are needed.
- The hard suite is in a usable band, around 50% in H1.
- Sonnet 26821's token saving persists on hard tasks.
- The ~300 s hangs are agent behaviour, and so are the 2400 s kills.

**Not yet:**
- Any claim about how 795, 913, 3052 or 5140 behave on hard tasks. Those rows are quarantined.
- Any per-task hard-suite effect treated as confirmatory. That needs a multiple-comparison rule first.
- Any Pi vs OpenCode result.
- Opus results for 26821.
- Step 8 batches after F03-2.
- Whether #193's watchdog timer fix changes anything. It is parked until after the reruns.
