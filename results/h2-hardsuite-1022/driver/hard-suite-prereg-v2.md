# Hard-task suite (H1/H2): pre-registration v2 (fixed 2026-10-22 ~2:20 PM ET, before any hard-suite run)
Supersedes hard-task-side-experiment-prereg.md (v1, sha 762dd598…), which is folded in: its 3 PRs and 3-control draw are kept.

## Rows (PR x model, each only on the model of its sheet row)
3052 Sonnet, 3052 Opus, 13331 Sonnet, 13331 Opus, 26821 Sonnet, 26821 Opus,
13090 Opus, 5140 Opus, 913 Opus, 4204 Opus, 1109 Sonnet, 795 Sonnet.
Controls: 3 OpenCode PRs with final Sonnet verdict "No effect detected" (exclude unconfirmed trigger, flagged, untestable),
drawn with sorted(int PRs) -> random.Random(20261017).sample(list, 3), run on Sonnet. Log input list + sha256.
Input list = verdicts in the sheet at draw time (draw happens at H2 start; log the sheet timestamp).

## Tasks (fixed): all 9 in data/packs/openbench-tb-hard/pack.toml
dna-insert, filter-js-from-html, model-extraction-relu-logits, polyglot-rust-c, regex-chess, sam-cell-seg,
torch-pipeline-parallelism, torch-tensor-parallelism, video-processing. No substitutions.

## H1 probe
2 cells per task on current OpenCode main, Sonnet and Opus. Output: cost/cell and hang rate per task. Not analysed for effects.

## H2 design
With vs without, interleaved-seeded, 10 per side per (row, task). Same exclusions as main study; hangs/timeouts = fail.
Primary: tokens per (row, task): effect = 95% CI excludes 0 AND point outside that model's A/A band
(Sonnet -6.5..+6.8; Opus OpenCode -3.2 [-10.4,+4.4] band edges as used in sheet). Also report tokens on completed cells only.
Pass rate: Fisher, reported only where pooled pass count is 2/10..8/10 per side; labelled screen-level.
Summary per row: "persists" = same-sign effect on >=2 tasks and no opposite-sign effect; "task-specific" = effect only on its
original task type; "reverses" = any opposite-sign effect. Controls are expected flat; any control effect is reported as a false-positive rate.
Parallel runs: if H2 runs concurrently with the main Sonnet run, log concurrency and start/end times per cell; both sides of
every comparison share the same interleaved schedule, so load affects both equally.

## Predictions
26821 persists (smaller system prompt on every request). 3052, 13331 flat unless the image/read path is exercised.
913, 4204, 795 uncertain. 1109 flat (edge-of-band result). Controls flat.

## Dated note, 2026-10-22 (no change to hypotheses, rows, or analysis)
- Hard-suite cells run on a CPU-only GCP VM with Docker exec, using the runner PR that adds hard-pack task selection and a configurable timeout. Model spend still goes through the Vertex proxy.
- The timeout cap is 2400 s on both sides, matching the earlier M4 hard runs. A cell that hits the cap counts as a fail.
- Both sides run interleaved on the same VM. Each cell records concurrency, start and end times, the VM type and the runner commit.
- H1 doubles as the setup check. Env failures there are fixed before H2 and are not scored. A task held back for disk is logged in DEFERRED.txt and run later, never dropped.

## Amendment A1, 2026-10-22 (made before any H1 or H2 result was seen)
- "Current OpenCode main" is replaced by a fixed pin: c10134729d (v1.18.31, PR 50272), the last 1.x-layout merge on our study list. Upstream main is now the 2.0 rewrite (v2.0.29), which our build and adapter cannot run. Every 1.x A/B in the study was measured on the 1.x layout, so testing on 2.0 would be a different question.
- H1 cost probe: 9 tasks x 2 runs x {Sonnet, Opus} on that pin, 36 cells.
- H2: each row keeps the same with/without builds as that PR's main-study A/B, so the only change is the tasks. Rows, hypotheses and analysis are unchanged.
- The 2 polyglot-rust-c smoke cells on PR #113 were a setup check and are not scored.
- A 2.0 adapter is out of scope here and would need its own pre-registration.

## Amendment A2, 2026-10-22 (made after H1, before any H2 cell)
- New cell status "blocked": the provider's content filter refused the run. Blocked cells are left out of pass rate and token analysis, like infra cells, and are counted and reported per side. If one side is blocked noticeably more often, that is reported as a finding.
- Torch's first-time download is baked into the shared image before H2, so both sides start from the same warm cache.
- H1 rescore: the 2 Opus dna-insert cells are blocked, not fails.
