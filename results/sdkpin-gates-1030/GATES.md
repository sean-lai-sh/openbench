# sdk-pin gate cells, 2026-10-30 (quarantine=sdkpin_gate_1030, gate_cell=true)

Task model-extraction-relu-logits, t1, image h2-env:1022 (sha256:72c59033...69ff), runner wt-gate = main c34b0e66 + #207 (e3746feb). OBENCH_GATE_CELL=1. Not scored data.

Total spend across all attempts: $5.0123 (total cap $5 reached; runs stopped there).

| pin | PR | model | pin_rule | pin_publish_ts | with | without | pair result | basis | stop reasons (w / wo) | out tokens (w / wo) | $ (w / wo) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2.0.0-beta.4 | 795 | sonnet | latest_at_build | 2025-07-07T10:25:45.447Z | pass | missing | INCOMPLETE | - | end_turn,tool_use / - | 8694 / - | 0.1923 / - |
| 2.0.0-beta.5 | 913 | opus | latest_at_build | 2025-07-10T13:29:12.295Z | pass | pass | PASS | parsed | end_turn,tool_use / end_turn,tool_use | 2833 / 6772 | 0.2277 / 0.3804 |
| 2.0.0-beta.11 | 1109 | sonnet | actual_installed | 2025-07-29T11:35:31.399Z | pass | pass | PASS | parsed | end_turn,tool_use / end_turn,tool_use | 8464 / 4619 | 0.2134 / 0.1817 |
| 2.0.0 | 4204 | opus | actual_installed | 2025-07-31T15:38:00.080Z | missing | missing | INCOMPLETE | - | - / - | - / - | - / - |
| 2.0.25 | 3052 | opus | latest_at_build | 2025-10-09T09:33:40.226Z | missing | pass | INCOMPLETE | - | - / end_turn,tool_use | - / 6144 | - / 0.4168 |
| 2.0.50 | 5140 | opus | lockfile | 2025-11-27T12:02:00.040Z | missing | missing | INCOMPLETE | - | - / - | - / - | - / - |
| 2.0.77 | 13331 | opus | actual_installed | 2026-04-17T03:45:51.890Z | missing | FAIL | FAIL | - | - / end_turn,tool_use | - / 11796 | - / 0.5498 |
| 3.0.64 | 26821 | opus | actual_installed | 2026-03-24T04:41:39.395Z | pass | pass | PASS | parsed | end_turn,tool_use / end_turn,tool_use | 6051 / 5881 | 0.2921 / 0.2620 |
| 3.0.71 | 26821 | opus | lockfile | 2026-04-16T19:46:13.907Z | pass | pass | PASS | parsed | end_turn,tool_use / end_turn,tool_use | 4093 / 3807 | 0.2260 / 0.3433 |

Notes:
- 2.0.0 (4204): not run in this attempt; the container-name clash with attempt1's stopped container made it exit at launch, and the $5 cap was then reached. attempt1/2.0.0 holds a partial run that I stopped by hand.
- 2.0.25, 2.0.50, 2.0.77: the $0.60 pair cap stopped them mid-pair (Opus pairs cost more than $0.60). 2.0.77 without: provider_pin_mismatch, loaded 2.0.58 != pin 2.0.77.
- 2.0.0-beta.4: attempt2/ is the first run, where the manifest overrode the pin and installed beta.11 (invalid). The rerun with e3746feb completed only the with side before the total cap.
- attempt1/: the first launch, preflight failures (missing worktrees).
- Unhandled chunk type hits: none

Follow-up (2026-10-30 21:45 EDT, no model calls):
- attempt1/ and attempt2/ rows now carry the gate fields, with gate_pass=false and gate_excluded=true. The first beta.4 run (attempt2/) is excluded: the manifest overrode the pin and installed 2.0.0-beta.11.
- The 4 PASS pins have installed_anthropic == pin on both arms. The loaded version is unproven on all 8 rows (strace off, provider_loaded_source=none).
- 2.0.77 / 13331: both builds (ba54cee55e, 847e06f9e1) statically import @ai-sdk/anthropic 2.0.58 (BUNDLED_PROVIDERS in provider.ts, declared in packages/opencode/package.json), so the binary embeds 2.0.58 and never loads the cache pin. This gate ran on ff501756 (#207 at 305d0139, before e3746feb) with pin_source=lockfile. e3746feb changes only manifest precedence, so it does not fix this build.
