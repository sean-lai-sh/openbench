# OpenBench reflection-loop pre-restart smoke report

**Verdict: FAIL for a full-pilot restart on `640f6751`.**
The earlier harness bugs (empty `/app`, host-side checkers, auto-rejected permissions / pending-tool early exits) look fixed. Three issues still block a full start: GCE metadata is reachable from trial containers, Carbon `sanitize-git-repo` was recorded as an infra `error` even though the checker ran and failed, and the Researcher's `checker_error` output-grep fix is not in this commit.

Times below are America/New_York. Commit: `640f675152bbbe31864bf47e14b81293aea249b7` (PR #265, `sea-111/cell-executor`), clean detached checkout in `~/wt-pilot-1`. OpenCode pin: `$HOME/h1/opencode-src/bin/ba54cee55e18b47fb70badc84ae2cbac7c83d258/opencode`. VM `thesis-h1-cpu` (us-central1-a) is now running and idle, with no tmux session and no obench containers. `~/pilot-1` and `~/pilot-2` were not touched. The full pilot was not started.

## What ran

Smoke A used `n_trials: 1` (supported by `RunConfig`). Config: `run_id=pilot-smoke-640f`, suite `pilot`, models `[gemini-4-carbon, claude-opus-5-5]`, `spend_cap_usd=100`, `--cell --use-image-tag --workers 8`, out `~/pilot-smoke-640f/run`, tmux `smoke640f`.

- Start: Tue Nov 17, 7:18 PM America/New_York (`2026-11-18T00:18:06+00:00`)
- Preflight: 20 trials, $35 estimate, within the $100 cap
- After the original 20 suite trials finished, the runner started a swap round because `fixed_tasks` was not set. Opus `polyglot-c-py` completed (fail). Five more swap trials were in flight. The runner was SIGINT/SIGTERM'd at 7:54 PM so the smoke would stay scoped to the planned 20. Those five dirs (`filter-js-from-html`, `regex-chess`, `video-processing` x2, Carbon `polyglot-c-py`) have wire/events but no row. They are invalid.

Smoke B: `run_id=pilot-smoke-640f-w1`, Opus only, `fixed_tasks: true`, tasks `adaptive-rejection-sampler`, `path-tracing`, `winning-avg-corewars`, `n_trials: 1`, `--workers 1`, out `~/pilot-smoke-640f-w1/run`, tmux `smoke640f-w1`.

- Start: 7:54 PM; done 8:18 PM America/New_York; EXIT 0; state `done`

## Spend

| Run | Trials with rows | Spend |
|---|---:|---:|
| Smoke A original 20 | 20 | $19.75 |
| Smoke A extra swap (Opus `polyglot-c-py`) | 1 | $0.22 |
| Smoke A total | 21 | $19.97 |
| Smoke B | 3 | $4.01 |
| **Combined** | **24** | **$23.98** |

## Table — Smoke A (workers=8)

| Model | Task | Status | Pass | Cost USD | Wall s | Steps | Error |
|---|---|---|---|---:|---:|---:|---|
| claude-opus-5-5 | adaptive-rejection-sampler | completed | False | 0.83 | 334 | 3 | |
| claude-opus-5-5 | dna-assembly | model_refused | — | 0.13 | 12 | 2 | model refused (refusal) at step 2 |
| claude-opus-5-5 | dna-insert | model_refused | — | 0.24 | 17 | 3 | model refused (refusal) at step 3 |
| claude-opus-5-5 | extract-elf | completed | False | 0.35 | 66 | 5 | |
| claude-opus-5-5 | model-extraction-relu-logits | completed | True | 0.34 | 118 | 4 | |
| claude-opus-5-5 | path-tracing | completed | True | 0.42 | 81 | 9 | |
| claude-opus-5-5 | polyglot-rust-c | completed | True | 0.22 | 65 | 5 | |
| claude-opus-5-5 | query-optimize | completed | False | 0.19 | 455 | 4 | |
| claude-opus-5-5 | sanitize-git-repo | completed | False | 0.42 | 63 | 9 | |
| claude-opus-5-5 | winning-avg-corewars | completed | True | 4.26 | 1436 | 70 | |
| gemini-4-carbon | adaptive-rejection-sampler | timeout | — | 4.09 | 1802 | 16 | agent timed out after 1800s |
| gemini-4-carbon | dna-assembly | provider_blocked | — | — | 9 | 0 | provider blocked: SAFETY |
| gemini-4-carbon | dna-insert | provider_blocked | — | — | 9 | 0 | provider blocked: SAFETY |
| gemini-4-carbon | extract-elf | provider_blocked | — | — | 14 | 0 | provider blocked: SAFETY |
| gemini-4-carbon | model-extraction-relu-logits | provider_blocked | — | — | 14 | 0 | provider blocked: SAFETY |
| gemini-4-carbon | path-tracing | completed | True | 1.22 | 394 | 12 | |
| gemini-4-carbon | polyglot-rust-c | completed | True | 1.43 | 871 | 12 | |
| gemini-4-carbon | query-optimize | timeout | — | 3.66 | 1802 | 34 | agent timed out after 1800s |
| gemini-4-carbon | sanitize-git-repo | error | — | 1.94 | 397 | 10 | trace_error: step_call_mismatch: 11 OpenCode steps but 10 main wire calls |
| gemini-4-carbon | winning-avg-corewars | timeout | — | — | 1802 | 13 | agent timed out after 1800s |
| claude-opus-5-5 | polyglot-c-py (swap, extra) | completed | False | 0.22 | 54 | 4 | |

Opus first-round completed: 4 pass / 4 fail, plus 2 `model_refused` (excluded). Carbon completed: 2 pass; 4 `provider_blocked`; 3 timeouts; 1 infra `error`.

## Table — Smoke B (Opus, workers=1)

| Task | Status | Pass | Cost USD | Wall s | Steps | vs workers=8 |
|---|---|---|---:|---:|---:|---|
| adaptive-rejection-sampler | completed | False | 1.88 | 596 | 15 | also completed fail at w=8 (334 s, 3 steps); not an early exit |
| path-tracing | completed | True | 0.67 | 83 | 9 | same as w=8 (81 s, 9 steps, pass) |
| winning-avg-corewars | completed | True | 1.46 | 741 | 27 | also completed pass at w=8 (1436 s, 70 steps); not an early exit |

## Checks

### (1) cell.json fields
Every Smoke A original trial and every Smoke B trial has `opencode_mount: standalone` and `agent_permissions: {doom_loop: allow, external_directory: allow, read: allow}`, and `workers` is 8 (A) or 1 (B).

`workspace_seed` has a `files` count and `hydrated_from` for all tb-mid / TB2 image tasks. All tb-hard / `default_image` (h1-env) trials record only `{"hydrated_from": null}` — that is what `seed_workspace()` returns on the `default_image` branch, which materializes the task workspace but does not write a file count. Those workspaces did contain task files (e.g. dna-insert `sequences.fasta`, polyglot-rust-c `.gitkeep` + agent output). Recording gap, not an empty `/app`.

### (2) Agent sees real `/app` files
- query-optimize (both models, A): `my-sql-query.sql` and `oewn.sqlite` appear in events/wire (and Opus also in trace). Carbon workspace also contained both files.
- winning-avg-corewars (Opus A and B; Carbon A): `warriors/` appears in events/wire (and Opus traces).

### (3) Checker placement
When a checker ran:
- tb-hard (`polyglot-rust-c`, `model-extraction-relu-logits`, Opus `dna-insert`): `checker-mode.txt` is `in_task_container`
- tb-mid / TB2 (`path-tracing`, `adaptive-rejection-sampler`, `query-optimize`, `winning-avg-corewars`, `sanitize-git-repo`, `extract-elf`, Opus `dna-assembly`): `self_containerized`

No checker file on Carbon `provider_blocked` or Carbon timeouts (expected). `h1-env:1027-strace` has `/usr/bin/bash` and `/usr/local/bin/python3` (bash 5.2.15, Python 3.13.17).

Host files created outside trial dirs during Smoke A: one `/tmp/.fbeffbbbffdb9eed-00000000.so` at start (4.3 MB). `file`/`strings` show a terminal/renderer library (createRenderer, setBackgroundColor, …), not agent task code. No leftover host agent processes after the run. VM is idle.

### (4) checker_error
**None** in A or B. No `command not found` in any checker output, so the known output-grep bug did not fire here. It still needs to be fixed before the full start (only docker launch exits 125/126/127 should be `checker_error`).

### (5) opencode-stderr.txt and auto-rejects
Written for every A and B trial. Almost all are 0 bytes. Two 77-byte files (Opus `model-extraction-relu-logits`, Carbon `sanitize-git-repo`) contain only uv "Resolving dependencies / Saved lockfile". **No auto-rejected permission lines.**

### (6) Pending-tool early exits
**None** at workers=8 or workers=1. No `agent_exit_pending_tool` or `harness_aborted` trials, and no `harness_abort.json` / `agent_exit.json`. The three previously early-exit tasks completed normally in both smokes.

### (6a / Researcher) Loops until timeout
**Opus:** no timeouts in A or B. No trial repeated an identical tool call 3+ times (max_repeat=1 everywhere, including Opus corewars at 70 steps).

**Carbon:** three trials hit the 1800 s agent timeout: `adaptive-rejection-sampler` (16 steps, 19 unique tool calls), `query-optimize` (34 steps, 35 unique), `winning-avg-corewars` (13 steps, 22 unique). `max_repeat=1` and `longest_consecutive_identical=1` on all three, so `looped_until_timeout=false`. They ran out of wall time on distinct calls; `doom_loop` did not produce identical-call loops in this smoke. Carbon `winning-avg-corewars` timeout has `cost_usd=null`.

### (7) Blocked / refused
Carbon `dna-insert`, `dna-assembly`, `model-extraction-relu-logits`, `extract-elf` are all `provider_blocked` with `blockReason=SAFETY`, in 9–14 s, no pass/fail. Opus `dna-insert` is `model_refused` at step 3 (`stop_reason=refusal`, category `bio`). Opus `dna-assembly` is `model_refused` at step 2 (same). path-tracing is not a 5th blocked task (Carbon path-tracing completed and passed).

### (8) ConnectionResetError
None in Smoke A or B `smoke.log`, run logs, or `opencode-stderr.txt`.

### (b) checker_error and pending-tool listing
Empty for both smokes: no `checker_error`, no `agent_exit_pending_tool`, no `harness_aborted`.

Related infra issue, not in those statuses: Carbon `sanitize-git-repo` (`2783e98991b0651d`) is `status=error`, `error=trace_error: step_call_mismatch: 11 OpenCode steps but 10 main wire calls`. `opencode_exit=0`, checker ran `self_containerized`, `checker_exit=1`. Checker output is a real pytest fail (3 failed tests, including `test_removal_of_secret_information`); no "command not found". There is no `harness_abort.json` / `agent_exit.json`. This would drop a real fail from the denominator if it happens in the pilot.

### Credentials (live inspect during Smoke A)

Inspected while running, 7:32 PM America/New_York:
- Carbon: `query-optimize` `8506b5f2840467eb` / `b0cc9cd2b4a7`
- Opus: `winning-avg-corewars` `3bf0aec528ed2893` / `3364d9a99a8c`
Shallow env/mount scan also covered the other still-running agent containers. Redacted notes: `cred-scan-redacted.txt`, `cred-scan-verdict.txt`.

**Env and mounts: clean (no real cloud credentials).**
- No `GOOGLE_*`, `GOOGLE_APPLICATION_CREDENTIALS`, `ANTHROPIC_*`, ADC paths, gcloud config dirs, service-account JSON, or access/refresh tokens in `docker inspect` Env, `docker exec env`, mounts, or mounted file contents.
- Mounts were only the trial workspace → `/app` (or `/app/dclm`) and the pinned OpenCode binary (read-only). No host home, `~/.config`, or docker.sock.
- The only `*.pem` hits inside images were certifi CA bundles (`pip/_vendor/certifi/cacert.pem`): false positives.
- `OPENCODE_CONFIG_CONTENT` contains a 15-character stub `apiKey` (sha256[:16]=`deb2c58180567ae2`, not a ya29/sk-/AIza/ghp_/AKIA/PEM prefix). It is hardcoded in `obench/reflection/vertex_models.py` (`opencode_config`) and used in tests as the proxy `x-api-key`. `baseURL` is `http://172.17.0.1:<port>/m/<model>/...`. This is a local-proxy stub, not a Vertex/ADC credential.

**Blocking network finding:** all four still-running agent containers used `network_mode=bridge`. TCP `connect_ex` to `169.254.169.254:80` returned 0 (reachable). No HTTP request was sent and no token was fetched. iptables had no rule blocking that address from docker0. If the GCE metadata HTTP API is usable, a trial could obtain the VM service-account token. That violates "credentials exist only in the host proxy," so this is a smoke FAIL even though the env/mount grep was clean.

## Fixes needed before the full restart

1. **Block GCE metadata (and other host credentials) from trial containers.** Env/mounts are clean; the Docker bridge still allows TCP to `169.254.169.254`. Isolate the agent network or drop metadata from docker0, while still allowing the host wire proxy.
2. **Land the Researcher's `checker_error` fix** (already requested): only docker launch exits 125/126/127; drop the "command not found" output grep. Not in `640f6751`.
3. **Do not classify a trial as infra `error` on `step_call_mismatch` when the checker already produced a verdict.** Carbon `sanitize-git-repo` would have been a completed fail (`checker_exit=1`).

Optional / non-blocking: record a `workspace_seed.files` count on the `default_image` path; record cost on agent timeouts (Carbon corewars was `$null`).

For a future 1-trial smoke, set `fixed_tasks: true` (or accept that `n_trials: 1` still starts swaps after round one).

## Full-restart command (do not run yet)

Wait for a commit that includes (1)–(3), Researcher OK on that exact head, then a clean detached checkout of that sha in `~/wt-pilot-1`. New dir `~/pilot-3/run`. Do not resume `~/pilot-smoke-640f` or `~/pilot-2`.

Config `~/pilot-3/config.json`:

```json
{
  "run_id": "pilot-3",
  "suite": "pilot",
  "suite_label": "repo pilot suite",
  "models": ["gemini-4-carbon", "claude-opus-5-5"],
  "spend_cap_usd": 5000,
  "n_trials": 30
}
```

```bash
export GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d
cd <HOME>/wt-pilot-1
# confirm: git rev-parse HEAD is the approved post-fix sha, and git status is clean
mkdir -p <HOME>/pilot-3
# write config.json as above
tmux new-session -d -s pilot3 "bash -lc '
  export GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d
  cd <HOME>/wt-pilot-1
  echo START \$(date -Iseconds) head=\$(git rev-parse HEAD)
  <HOME>/venv/bin/python -m obench.reflection.runner \
    --config <HOME>/pilot-3/config.json \
    --out <HOME>/pilot-3/run \
    --cell \
    --opencode <HOME>/h1/opencode-src/bin/ba54cee55e18b47fb70badc84ae2cbac7c83d258/opencode \
    --use-image-tag \
    --workers 8
  echo EXIT \$? \$(date -Iseconds)
' > <HOME>/pilot-3/pilot.log 2>&1"
```

Preflight at n_trials=30, 10 tasks, 2 models, default estimates ($1.50 Carbon / $2.00 Opus) is the same as pilot-2: 600 first-round trials, $1050 estimated, $3150 worst case, within a $5000 cap. About 12–15 hours at 8 workers.
