# PR #243 gate checks, 2026-11-12 (America/New_York)

Runner head under test: `151e349cbe6edd40855273115502f5ac2d7f54a9` (branch `cursor/opencode-sonnet-model-eddf`).
Base / merge-base: `39875fac6670b24c1cef2635aaf077e5c6e04741` (main). Data only; no code change.

## 1. Unit suite on thesis-h1-cpu-2 (`unit-h1cpu2/`)

`python -m unittest discover -s obench/tests -v` in a fresh venv with `pip install -e .`, API/GCP env vars unset (same as PR PROOF.md).

- `run2-full/` is the result to use: standalone clone (no sparse checkout), umask 022, base then PR run sequentially in the same checkout.
  - base 39875fac: 2327 tests, 1 failure, 81 errors, 1 skip
  - PR 151e349c: 2336 tests, 1 failure, 82 errors, 1 skip
  - 1 F + 81 E on both heads are the publish PII check: `[username] box` (this VM's user is `box`, and the word appears in generated `index.html`). Same set as the PR's proof (there the trigger was hostname `cursor`).
    Modules: test_site 64, test_leaderboard 13, test_community 4, test_publish 1 (FAIL: test_cli_publish_and_verify_e2e).
  - The 1 extra PR error is `test_stall_kill.StallTerminationTests.test_successful_local_worker_reaps_descendants_and_preserves_result` ("local adapter worker process group survived bounded cleanup"). Flaky on both heads: 5 isolated reruns failed 3/5 at PR and 1/5 at base (`stall-kill-rerun.log`). PR does not touch obench/run.py.
  - No failure is new in this PR.
- `run1-sparse/` is the first attempt, kept for the record and not used: worktrees of `~/ob` inherited `sparse-checkout !/results/`, the two suites ran in parallel and umask was 0002. That added 10 environment failures (missing results/ files, group-writable site dir, and a shared `~/.openbench-test-persist-auth.json` race).
- `obench validate --no-imported` (PR head): exit 1. 8 FAIL rows, all `trig-omp-*` (bugfix-regress, callsites, fanout, multiedit, multistep, netclient, reported, unusedparam). Solution checkers fail with `No module named pytest`; pytest is absent from both the venv and system python3 on the VM (`run1-sparse/pytest-check.txt`). trig-lsp-csharp is `infra` both sides (no dotnet) and counts PASS. Same as the PR's validate.log.

## 2. Sonnet smoke on thesis-h1-cpu-3 (`d1fu-smoke243-1112/`)

Image h2-env:1022@sha256:72c59033…, prebuilt binaries `/h1/opencode-src/bin/<sha>/` (without c436fc69, with d7af1f17), task trig-tmpdir (PR 725226), seed 1016, trials 1/side, jobs 2, `--max-cost-usd 3` per form. `launch-s243.sh`, `cell.sh`.

- `A-model-vertex/`: `--model claude-sonnet-5-5 --vertex-model claude-sonnet-5-5` (the follow-up's form)
- `B-model-only/`: `--model claude-sonnet-5-5` (no --vertex-model)

| form | arm | -m | upstream per request | requests / traced / untraced | cache_read per call | thinking tokens per call (upstream) | cost | wall |
|---|---|---|---|---|---|---|---|---|
| A | without | anthropic/claude-sonnet-5-5 | sonnet ×3 | 3/3/0 | 0, 0, 15220 | 0, 83, 0 | $0.0847 | 13.5 s |
| A | with | anthropic/claude-sonnet-5-5 | sonnet ×4 | 4/4/0 | 0, 0, 0, 0 | 0, 0, 43, 0 | $0.1603 | 13.5 s |
| B | without | anthropic/claude-sonnet-5-5 | sonnet ×4 | 4/4/0 | 0, 0, 0, 15969 | 0, 68, 0, 0 | $0.1258 | 15.2 s |
| B | with | anthropic/claude-sonnet-5-5 | sonnet ×3 | 3/3/0 | 0, 0, 0 | 0, 44, 0 | $0.1206 | 11.7 s |

Total spend $0.4913. Row `model`, `requested_model`, `protocol_model`, `upstream_model` = claude-sonnet-5-5 on all 4 cells; `upstream_model_mixed` false; endpoint global.

**All 4 cells are `failure_class: infra`, `provider_pin_mismatch: loaded 3.0.71 != pin 3.0.64`.** The agent finished the task (final answers present), but the checker was not run. Cause: the build.ts `--single` prebuilt binaries use a *bundled* `@ai-sdk/anthropic` 3.0.71 (log: "using bundled provider"), and `packages/opencode/package.json` at c436fc69 pins 3.0.71, but the runner takes the pin from `bun.lock` and reads the 3.0.64 entry (`pin_source: lockfile`). Not caused by #243 (model-independent); it would hit Opus cells with these binaries too. Blocks the 30/side follow-up as is.

Other observations:
- `--variant medium` is on cmd, but the proxy saw `thinking_sent: none` on every request (no thinking/effort param upstream). Sonnet still returned 43–83 thinking tokens on one call per cell (signed thinking blocks are in the session DB). Same `none` as D1 1022 Sonnet and earlier Opus rows. The cell's `tokens_reasoning` is 0 / `tokens_proxy_reasoning` null, so these thinking tokens are not counted on the row.
- Cache reads did not appear from call 2. Calls 1–2 (and 1–4 in A/with) each wrote ~15.2–15.9K. Same pattern as `results/d1-25226-split-1022-smoke` (0, 0, 15211) and the Opus 25226 rows; not new in #243.
- Context limit: the cell's generated OpenCode config is not saved. Reproduced at 151e349c (`config-check.txt`): the assessed proxy entry is `claude-opus-5-5 {context 1000000, output 128000}`. `--model claude-sonnet-5-5` renames it to `claude-sonnet-5-5` with the same 1,000,000/128,000 limits. Opus keeps 1,000,000/128,000 unchanged. So the effective Sonnet limit is **1M, not 200K**, the same limit earlier opus-labelled Sonnet runs had.
- OpenCode logged `NpmInstallFailedError @opencode-ai/plugin@0.0.0-default-…` for the config dir (prebuilt version string has no npm release). It was a warning and the run continued.

Scrub: `python obench/scrub.py <transcripts> --check` reports only `[base64-blob]` hits (signed thinking blocks in `opencode-default.db-wal`, a ripgrep release URL). No username, home, hostname or email hits in transcripts. Hits outside transcripts are commit ids/digests and the VM hostname `thesis-h1-cpu-3` in cell `host` fields. No file is over 50 MB, so there is no MANIFEST.
