# Set-aside 17 report (round 2 @ e04d456 / PR #6)

Smoke #17098 A/A passed first. Driver `results/ab-logs/setaside2.sh`, CAP=900.

# Set-aside 17 report (auto-generated)

Worktree /workspace/openbench-ab @ e04d456 (PR #6) [round 2]. Driver: results/ab-logs/setaside2.sh. Command: `python3 -m thesis.ab.run_ab thesis/ab/fixtures/opencode-harness-prs.csv --pr <PR> --trials 3 --jobs 8 --out results/ab --cache /workspace/openbench-ab/results/opencode-src`.

Cumulative est. spend (all phases): $432.34 (baseline before set-aside ≈ $414; phase soft cap ~$400 / overall ~$800–1000).

Noise floor (from A/A+controls): ±12% wall, ±19% tokens, ±11% cost. CLEAR = at least one metric outside the band.

| PR | n (b/a) | Pass b→a | Wall s b→a (Δ%) | Turns b→a | Tok/cell b→a (Δ%) | $/cell b→a (Δ%) | PR $ | SDK changed | vs noise |
|---|---|---|---|---|---|---|---|---|---|
| 623 | 24/24 | 1.000→1.000 | 41.2→43.2 (+4.8%) | n/a→n/a | 181k→191k (+5.5%) | 0.219→0.199 (-9.3%) | 10.04 |  | within |
| 913 | — | — | — | — | — | — | — |  | without: preflight exited before any metered call: exit 1: [0m █▀▀█ █▀▀█ █▀▀ █▀▀▄ [0m█▀▀ █▀▀█ █▀▀▄ █▀▀ █░░█ █░░█ █▀▀ █░░█ [0m█░░ █░░█ █░░█ █▀▀ ▀▀▀▀ █▀▀▀ ▀▀▀ ▀ ▀ [0m▀▀▀ ▀▀▀▀ ▀▀▀ ▀▀▀ [0m [1m> Reply with ok ; with: preflight exited before any metered call: exit 1: [0m █▀▀█ █▀▀█ █▀▀ █▀▀▄ [0m█▀▀ █▀▀█ █▀▀▄ █▀▀ █░░█ █░░█ █▀▀ █░░█ [0m█░░ █░░█ █░░█ █▀▀ ▀▀▀▀ █▀▀▀ ▀▀▀ ▀ ▀ [0m▀▀▀ ▀▀▀▀ ▀▀▀ ▀▀▀ [0m [1m> Reply with ok |
| 984 | — | — | — | — | — | — | — |  | without: preflight exited before any metered call: exit 1: [0m █▀▀█ █▀▀█ █▀▀ █▀▀▄ [0m█▀▀ █▀▀█ █▀▀▄ █▀▀ █░░█ █░░█ █▀▀ █░░█ [0m█░░ █░░█ █░░█ █▀▀ ▀▀▀▀ █▀▀▀ ▀▀▀ ▀ ▀ [0m▀▀▀ ▀▀▀▀ ▀▀▀ ▀▀▀ [0m [1m@ [0manthropic ; with: preflight exited before any metered call: exit 1: [0m █▀▀█ █▀▀█ █▀▀ █▀▀▄ [0m█▀▀ █▀▀█ █▀▀▄ █▀▀ █░░█ █░░█ █▀▀ █░░█ [0m█░░ █░░█ █░░█ █▀▀ ▀▀▀▀ █▀▀▀ ▀▀▀ ▀ ▀ [0m▀▀▀ ▀▀▀▀ ▀▀▀ ▀▀▀ [0m [1m@ [0manthropic |
| 1248 | — | — | — | — | — | — | — |  | without: preflight exited before any metered call: exit 1: [0m █▀▀█ █▀▀█ █▀▀ █▀▀▄ [0m█▀▀ █▀▀█ █▀▀▄ █▀▀ █░░█ █░░█ █▀▀ █░░█ [0m█░░ █░░█ █░░█ █▀▀ ▀▀▀▀ █▀▀▀ ▀▀▀ ▀ ▀ [0m▀▀▀ ▀▀▀▀ ▀▀▀ ▀▀▀ [0m [1m@ [0manthropic ; with: preflight exited before any metered call: exit 1: [0m █▀▀█ █▀▀█ █▀▀ █▀▀▄ [0m█▀▀ █▀▀█ █▀▀▄ █▀▀ █░░█ █░░█ █▀▀ █░░█ [0m█░░ █░░█ █░░█ █▀▀ ▀▀▀▀ █▀▀▀ ▀▀▀ ▀ ▀ [0m▀▀▀ ▀▀▀▀ ▀▀▀ ▀▀▀ [0m [1m@ [0manthropic |
| 2334 | 24/24 | 0.000→0.000 | 5.5→4.6 (-16.0%) | n/a→n/a | 16k→16k (-0.3%) | 0.048→0.028 (-41.1%) | 1.81 |  | CLEAR |
| 2367 | 24/24 | 0.000→0.000 | 4.8→4.6 (-3.7%) | n/a→n/a | 16k→16k (+0.2%) | 0.026→0.026 (+2.1%) | 1.24 |  | within |
| 3052 | 24/24 | 0.000→0.000 | 4.8→4.6 (-4.9%) | n/a→n/a | 16k→16k (-0.0%) | 0.050→0.055 (+9.3%) | 2.51 |  | within |
| 3115 | 24/24 | 0.000→0.000 | 4.8→4.8 (-0.7%) | n/a→n/a | 16k→16k (+0.0%) | 0.027→0.046 (+68.4%) | 1.75 |  | CLEAR |
| 3369 | — | — | — | — | — | — | — |  | with: provider stream error with no metered tokens: {"type":"error","timestamp":1791229254084,"sessionID":"ses_ef26aaef5fferMtild3rUP4L94","error":{"name":"UnknownError","data":{"message":"Error: Unhandled  |
| 3418 | — | — | — | — | — | — | — |  | without: provider stream error with no metered tokens: {"type":"error","timestamp":1791229269195,"sessionID":"ses_ef26a753affedpyRSGUa5EwH5X","error":{"name":"UnknownError","data":{"message":"Error: Unhandled  |
| 4204 | — | — | — | — | — | — | — |  | without: exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/0d3d48bb5964a95e939edcea3bb726a21823d1a1/opencode' ; with: exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/963a926db24ea70f6002cde66d0ff858de06fae2/opencode' |
| 4838 | — | — | — | — | — | — | — |  | without: exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/ff609a52c13fa0444cb338d35fb16a07a820b539/opencode' ; with: exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/aaa31f02af5cd1d90e11549ee7b291e2f2a913d2/opencode' |
| 5066 | — | — | — | — | — | — | — |  | without: exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/350a32274a24e6f5ca3ea30be114a8171a58270f/opencode' ; with: exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/a607f33552b653af5e7ab5233c2da3389b978e68/opencode' |
| 5131 | — | — | — | — | — | — | — |  | without: exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/40eb8b93e132daac1dff63e260cb61a880a2ba4d/opencode' ; with: exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/ba417d80b1174d0e289d8fc91c77a8f6a0d592f4/opencode' |
| 5140 | — | — | — | — | — | — | — |  | without: exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/3a179fcd34aed5d91b6dd0c522bec419494356db/opencode' ; with: exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/75a4dcbce833a318b825f2310444337910d0cc3a/opencode' |
| 5527 | — | — | — | — | — | — | — |  | without: exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/6d412d8872adda1e059f284bc591d3928eebeef5/opencode' ; with: exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/92948ed8a49a2701ffa353c93a271a66e9637f99/opencode' |
| 6524 | — | — | — | — | — | — | — |  | without: exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/decc616c800827e1e28c96fe2253ee229095dc23/opencode' ; with: exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/f3db96631704f5d7cf2ee6c2a31812d161305356/opencode' |

## Clears noise floor
2334, 3115

ConnectionReset note: see per-PR setaside2-<pr>.log CR counts.

## ConnectionResetError findings

- Smoke #17098 A/A (modern merge build, both sides): **0** ConnectionResetError.
- Set-aside round 2 (all 17 PRs on e04d456): **0** ConnectionResetError across every `setaside2-<pr>.log`.
- Prior aborted `setaside-2334.log` (aecd3fa / mid-kill): **8** ConnectionResetError lines — consistent with client disconnect during kill -9, not a systematic modern-build flood.

**Conclusion:** ConnectionResets did **not** hit the modern smoke build or the relaunch of the 17 on e04d456. Earlier CR noise was from the aborted kill path. Old builds that scored (623/2334/2367/3052/3115) also had CR=0 while metering via `proxy_measured`.

## Metering / outcomes summary

| Bucket | PRs | Notes |
|---|---|---|
| Metered OK (`proxy_measured`) | 623, 2334, 2367, 3052, 3115 | No false infra for missing meters; PR #6 working |
| Preflight exit 1 | 913, 984, 1248 | launched 0 |
| Provider stream incompatible | 3369, 3418 | partial cells; stream errors |
| Missing binary ENOENT | 4204, 4838, 5066, 5131, 5140, 5527, 6524 | musl-era SHA cluster; launched 0 |

## Quarantine

Aborted unmetered set-aside cells for 623/913/984/1248 (+2334-partial) under `results/ab-quarantine/setaside-aborted-2026-10-05/`. Exclude from score/noise. Good phase-2 rows left in `results/ab/`.

Spend: cumulative est. **$432.34** (prior ~$414; setaside2 phase delta ~$19 because many PRs launched 0). Soft cap not hit.


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
