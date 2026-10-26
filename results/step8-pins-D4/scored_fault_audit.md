# Step-8 scored-cell provider-fault audit (full logs)

Script: `thesis/ab/audit_scored_faults.py`, which reads every cell's full `agent-output.txt` (opencode `--print-logs`) plus `log/*.log` as bytes. Output: `scored_fault_audit.csv`, one row per cell. Read-only: no model spend, no pins, VM not started (every full log is already on the box).

Signatures: Unhandled chunk type, Unsupported model version, stream error, AI_APICallError, overloaded_error, api_error, AI_*Error, InitError/UnknownError. Bad-key lines (authentication_error / invalid x-api-key) are excluded. AI_TypeValidationError is counted separately.

## Hits per run

| run | cells | signature-hit cells | provider-fault cells | AI_TypeValidationError cells |
|---|---|---|---|---|
| F01 | 1169 | 31 | 2 | 22 |
| F02 | 1082 | 0 | 0 | 0 |
| F02-rerun | 180 | 0 | 0 | 0 |
| F03 | 245 | 0 | 0 | 0 |
| F03-1-rerun | 181 | 0 | 0 | 0 |
| pilot447-full | 539 | 0 | 0 | 0 |
| VM F03-1 pinned (#144) | 240 | 0 | 0 | 0 |

Of the 31 F01 hits, 29 are model tool misuse, not provider faults:
- AI_InvalidToolInputError: 1287 make-ci-green, with ×12 and without ×10; 775 without trial 14 (solved).
- AI_NoSuchToolError ("tried to call unavailable tool 'task'"): 775 trig-todo-task, with 6/9/25 and without 3/6/18.

The 2 provider/transport faults:
- `full413-1020-F01/runs/F01/579/transcripts/without/trig-read-lines/27/agent-output.txt:360`, outcome **hang**: `service=session error=TimeoutError: The operation timed out. stream error`. Already non-scored (hang). This is a stream timeout, so it could be reclassified as infra.
- `full413-1020-F01/runs/F01/1545/transcripts/without/trig-lsp-ts/22/agent-output.txt:102`, outcome **wrong_answer**: `"error":{"name":"UnknownError","data":{"message":"SyntaxError: Failed to parse JSON"}}`. **Candidate to reclassify as infra.**

No scored cell in these runs has Unhandled chunk type, Unsupported model version, overloaded_error, api_error, or AI_APICallError. The 9 chunk-error cells from #153 are all in the quarantined run (step8-vm-F03-1-1025-QUARANTINED).

Correction to #153: the quarantined run's full logs do show the install. `3185/transcripts/with/trig-subagent-resume/1/agent-output.txt:59,73` has `pkg=@ai-sdk/anthropic version=latest installing` → `installed @ai-sdk/anthropic@4.0.88`. So 4.0.88 is **confirmed from logs**, not inferred. The earlier rg search missed it because rg skips files it detects as binary (ANSI bytes).

## #143 pin check: what it verifies

It checks the **on-disk version in the per-cell opencode cache**, not the runner's install log:
- `obench/adapters/opencode.py:480-508` `_ensure_provider_sdk`: sets OPENCODE_DISABLE_DEFAULT_PLUGINS=1 and OBENCH_PROVIDER_PINS, and seeds `$XDG_CACHE_HOME/opencode` through `seed_cell_cache`.
- `thesis/ab/provider_pin.py:393-441` `seed_cell_cache`: refuses non-exact pins. It copies the locked template and returns `mismatch_reason(cell_cache)`.
- `thesis/ab/provider_pin.py:233-265, 284-315`: `installed_packages` / `mismatch_reason` read `node_modules/@ai-sdk/*/package.json` `version` and report missing/drifted/empty as `provider_pin_mismatch`.
- Post-run, `obench/adapters/opencode.py:1360-1366` `_observe` (`_provider_sdk_drift` at 553-562, `_resolved_provider_versions` at 468-477) re-reads the cache after the cell. That gives `provider_versions` and `sdk_drift`.
- Live, `thesis/ab/watch.py:245-260` with `provider_pin.py:317-328` `violation_in_text` aborts on any `version=latest` / `@latest` line in opencode output.
- Runner: `thesis/ab/run_ab.py:1732-1790` (`_overlay_provider_pin`, `_fail_closed_unpinned`, called at 2061-2063) makes an unpinned opencode cell infra before launch.
- `/workspace/s8q/preflight.py` only checks that a pin exists for sha+side (lines 8-9, 16, 42-57), plus src/bun. It does not check versions.

Limit: none of these proves which module the opencode process actually `import`ed. What they prove: the cache held the pin before and after the cell, and opencode logged no install or latest resolution.

## #144 VM pinned rerun, 240 cells

Item 3 was conditional on the check being install-log-only, which it isn't. The full logs were cross-checked anyway:
- `provider_versions` = `{"@ai-sdk/anthropic":"2.0.0"}`: 240/240 (post-run on-disk). No `sdk_drift` field. `pin_sha256` 1c264120… on all 240. (`version_drift`=True on all rows is the host CLI-pin drift flag from `obench/run.py:142`, not the SDK.)
- opencode `getSDK` completed: 240/240. opencode `@ai-sdk/anthropic` install lines: 0/240. `version=latest` / `@latest`: 0/240. "Unsupported model version": 0/240.
- Result: **2.0.0/v2: 240, other: 0**. The quarantined run had a `version=latest installing` line at getSDK. The pinned run has none, so the pre-seeded 2.0.0 cache was used.
