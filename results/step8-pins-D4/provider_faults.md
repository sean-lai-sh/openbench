# Step-8 infra/hang cells by provider version: provider faults vs timeouts (2026-10-26)

Read-only follow-up to #151. Script: `thesis/ab/classify_provider_faults.py`. Per-cell rows: `provider_faults.csv` (version, failure_class, classification, file, line, task, trial, run_id, snippet).

## How cells are classified
- Scope: step-8 cells (results/step8-*/**/*.jsonl, transcripts and proxy-ledger excluded) with failure_class `infra` or `hang`.
- Text searched: `error`, `infra_reason`, `provider_error`, `requests_error`, `hang_reason` and `output_tail`, which holds the opencode log tail.
- The checks run in this order, and the first match wins:
  1. `other:auth` — `authentication_error|invalid x-api-key`
  2. `other:install` — `bun\W+add|NpmInstallFailedError|No matching version found`
  3. `provider_fault` — `Unhandled chunk type|AI_\w*Error|APICallError|TypeValidationError|stream error|overloaded_error|api_error|invalid_request_error`
  4. `timeout` — `no_progress|idle_s|timed out|timeout|ETIMEDOUT|ECONNRESET|Connection`
  5. `other` — anything left.
- Auth and install are checked first because they match the SDK names without being provider faults. One cell is an `AI_APICallError` caused by a bad key in a smoke run; others are a runner `bun add @ai-sdk/anthropic@pin` traceback or a log line naming `pkg=@ai-sdk/anthropic`.

| version | infra | provider fault | timeout (infra) | other (infra) | hang (all timeout) |
|---|---|---|---|---|---|
| 2.0.0 | 3 | 0 | 0 | 3: 2 install (runner `bun add` pin traceback: F01 1761 make-it-run t2, pilot 2577 taskflow t16), 1 `exit 1` usage | 15 |
| 2.0.0-beta.11 | 4 | 0 | 4 (3 no_progress, 1 urlopen timeout) | 0 | 9 |
| 2.0.0-beta.13 | 5 | 0 | 3 | 2: 1 auth (smoke 1443 trig-read-lines t1, AI_APICallError invalid x-api-key), 1 `exit 1` usage (F01 1689) | 1 |
| 3.0.64 | 1 | 0 | 0 | 1 install (pilot 25667 make-it-run t5, NpmInstallFailedError @opencode-ai/plugin) | 13 |
| 3.0.71 | 2 | 0 | 0 | 2 install (pilot 40990 make-it-run t20, same plugin error) | 2 |
| unrecorded | 7 | 7 | 0 | 0 | 0 |

Notes:
- No recorded-version cell has a provider fault.
- The only provider faults are the 7 `Unhandled chunk type: custom` cells in `step8-vm-F03-1-1025-QUARANTINED`: 3185 with trig-subagent-resume t1–3, 3192 with trig-bash-limits t1–2, 3192 without trig-bash-limits t1–2.
- Those cells carry no version. `provider_pins.json` (from #143) records those VM sides as 2.0.0 (`pin_source=vm_quarantine_log`), so they are attributable to 2.0.0. The pinned rerun at 2.0.0 (#144) had none.
- The 25 `provider_pin_mismatch: empty cache` cells (VM F03-1 pinned, version "missing") are outside this table. They are a fail-closed pin check, not a provider fault.

## Addendum (2026-10-26): chunk-error cells, which version, and 9 vs 7
**Count.**
- 9 cells in `step8-vm-F03-1-1025-QUARANTINED` hit `Unhandled chunk type: custom`:
  - 3185 with, trig-subagent-resume trials 1–3;
  - 3192 with, trig-bash-limits trials 1–3;
  - 3192 without, trig-bash-limits trials 1–3.
- 7 are `failure_class=infra`. 2 (3192 with and without, trial 3) were scored `wrong_answer`, so the first version of this table, which only covered infra/hang, left them out.
- 9 is the right number of cells. They are not duplicates or retries: each has its own session id, e.g. 3192 without trial 3 is `ses_e89ac0f97ffeLQMd75hrROd1hv`.
- The script now also keeps non-infra cells that hit `Unhandled chunk type`. Other provider patterns appear in normal transcripts (e.g. a tool-error field name), so matching them broadly produced false positives.
- Each row's text has the error up to 3 times (the ERROR log line, the JSON error event, and the error field). So counting log lines gives about 25, not 9.

**Version.**
- These cells carry no `provider_versions` and are flagged `version_drift=true`.
- The runner log `runs/F03-1/F03-1.log` has `installed @ai-sdk/anthropic@2.0.0` before each cell (e.g. lines 41, 47, 58). That is the runner's `bun add` pin, not what opencode loaded.
- The 3 cells from 3185 with have, in their `output_tail`: `error=Unsupported model version v4 for provider "anthropic" … AI SDK 5 only supports models that implement specification version "v2"`. So the provider opencode actually loaded implemented spec v4 (a 4.x package), not 2.0.0. This is column `spec_seen`.
- The `output_tail` of the 3192 cells (with and without) is cut at 2000 characters and has no version line.
- No "installed 4.0.88" line exists in the data committed for this run. npm shows 4.0.88 as `latest`, published 2026-10-24 17:58Z, the last 4.x release before the run (2026-10-26 03:41Z). So 4.0.88 is consistent but **inferred, not directly shown** in the box copy.
- The opencode-side install log would be in the VM's own opencode log. I did not start the VM to read it (no spend).
- `version` stays `unrecorded`. The new columns are `log_installed` (empty for all 9) and `spec_seen`.

**Not counted here:**
- 29 beta.11 cells (28 wrong_answer, 1 solved) contain `AI_TypeValidationError`. Those are tool-input validation errors the session recovered from, not cell failures.
- They are excluded from the provider_fault counts, but they show up if PROV is applied to every cell.
