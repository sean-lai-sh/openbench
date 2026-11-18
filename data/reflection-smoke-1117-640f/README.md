# FAIL — reflection pre-restart smoke at `640f6751` (17 Nov 2026). Do not pool.

**This is a gate smoke, not pilot data. None of these trials may be pooled with later runs or used in pilot tables, pass rates, the swap rule, credit assignment, or ideation.**

**Verdict: FAIL as a restart gate.** Trial containers could open a TCP connection to the GCE metadata server at `169.254.169.254:80`. No HTTP request was sent and no token was fetched, but an agent could have obtained the VM service-account token. Env and mounts were otherwise clean (no `GOOGLE_*`, Anthropic, ADC, or gcloud material).

`rebuild_tables` will not pick this folder up on its own. The runner only rewrites tables inside an explicit run directory, and `--out` must be outside `results/` and `data/`. Do not point `--out` or `--run` at this folder.

## Run

| | |
|---|---|
| Head | [#265](https://github.com/sean-lai-sh/openbench/pull/265) at `640f675152bbbe31864bf47e14b81293aea249b7` (clean checkout) |
| Host | `thesis-h1-cpu` (project `nyu-rdg-fy26-js11531-a68d`, zone `us-central1-a`) |
| Window | 17 Nov 2026, 7:18 PM to 8:18 PM America/New_York |
| Combined spend | **$23.98** (verified $23.9834 from `trials.jsonl`) |
| OpenCode pin | `ba54cee55e18b47fb70badc84ae2cbac7c83d258` (scrubbed launchers show this hash as `<REDACTED_HEX>`) |
| VM copy | Read-only; `~/pilot-1` and `~/pilot-2` were not touched. Workspaces were not copied and remain on the VM. |

### Smoke A (`smoke-a/`, `run_id=pilot-smoke-640f`)

1 trial per task per model, Carbon and Opus mixed, `--workers 8`, spend cap $100, out `~/pilot-smoke-640f/run`.

- Started 7:18:06 PM America/New_York (`2026-11-18T00:18:06+00:00`).
- Preflight: 20 trials, $35 estimate, within the $100 cap.
- After the original 20 suite trials finished, the runner started a swap round because `fixed_tasks` was not set. Opus `polyglot-c-py` completed (fail, $0.22). Five more swap trials were in flight when the runner was stopped at 7:54 PM so the smoke would stay scoped to the planned 20. Those five directories are **INVALID**.

### Smoke B (`smoke-b/`, `run_id=pilot-smoke-640f-w1`)

Opus only, `fixed_tasks: true`, tasks `adaptive-rejection-sampler`, `path-tracing`, `winning-avg-corewars`, `--workers 1`, out `~/pilot-smoke-640f-w1/run`.

- Started 7:54 PM; finished 8:18:29 PM America/New_York (`2026-11-18T01:18:29+00:00`); EXIT 0; state `done`.

## Verified counts (from `trials.jsonl`)

These match the PM report.

| Run | Rows | Spend (USD) |
|---|---:|---:|
| Smoke A original 20 suite trials | 20 | 19.7543 (reported as $19.75) |
| Smoke A extra swap (Opus `polyglot-c-py`) | 1 | 0.2161 (reported as $0.22) |
| Smoke A total | **21** | **19.9703** (reported as $19.97) |
| Smoke B | **3** | **4.0131** (reported as $4.01) |
| **Combined** | **24** | **23.9834** (reported as **$23.98**) |

Every row has `code_commit=640f675152bbbe31864bf47e14b81293aea249b7`. Smoke A rows have `workers=8`; Smoke B rows have `workers=1`. No `retried_4xx` entries.

### Smoke A results

- **Opus:** of the 8 completed non-refused first-round trials, 4 passed (`model-extraction-relu-logits`, `path-tracing`, `polyglot-rust-c`, `winning-avg-corewars`) and 4 failed. `dna-assembly` was `model_refused` at step 2; `dna-insert` was `model_refused` at step 3. The extra swap `polyglot-c-py` completed as a fail.
- **Carbon:** 2 passes (`path-tracing`, `polyglot-rust-c`). 4 `provider_blocked` with `blockReason=SAFETY` as expected (`dna-insert`, `dna-assembly`, `extract-elf`, `model-extraction-relu-logits`), in 8.7–13.9 s. 3 hit the 1800 s timeout (`adaptive-rejection-sampler`, `query-optimize`, `winning-avg-corewars`). `sanitize-git-repo` (`2783e98991b0651d`) is recorded as infra `error` (`trace_error: step_call_mismatch: 11 OpenCode steps but 10 main wire calls`) even though the checker ran (`self_containerized`, `checker_exit=1`) and failed 3 tests. That is a real fail being dropped from the denominator. Carbon corewars timeout has `cost_usd=null`.

### Smoke B results (Opus, 1 worker)

- `adaptive-rejection-sampler`: completed fail (596 s, 15 steps); also a completed fail at 8 workers, not an early exit.
- `path-tracing`: pass (83 s, 9 steps); same outcome as 8 workers.
- `winning-avg-corewars`: pass (741 s, 27 steps); also a pass at 8 workers, not an early exit.

## INVALID — Smoke A in-flight swap directories

These five directories have `wire.jsonl` / events but no `cell.json` and no `trials.jsonl` row. They were still running when Smoke A was stopped. Each contains an `INVALID.txt`. Do not score or pool them.

| Model | Task | Trial id |
|---|---|---|
| claude-opus-5-5 | filter-js-from-html | `b3c15a08f9337204` |
| claude-opus-5-5 | regex-chess | `85041efc5f9ddea6` |
| claude-opus-5-5 | video-processing | `7c9a7f5a162c6c0a` |
| gemini-4-carbon | polyglot-c-py | `ecc76946560ea86a` |
| gemini-4-carbon | video-processing | `334e7e8d99860f96` |

## What the smoke showed was fixed

Every trial saw the image's real `/app` files. Checkers ran `in_task_container` for tb-hard and `self_containerized` for tb-mid/TB2. No permission prompts were auto-rejected. There were no pending-tool early exits at 8 workers or at 1, and no `checker_error`, `agent_exit_pending_tool`, `harness_aborted`, or `ConnectionResetError`. The OpenCode mount was `standalone` on every trial. Neither model looped until timeout (`max_repeat=1` everywhere). Env and mounts had no real cloud credentials.

## Open blockers before a full restart

1. **Block the GCE metadata server from agent and checker containers** (checkers run agent code). A preflight must actually try to reach `169.254.169.254` from both an agent and a checker container and refuse to start if the request connects. Checking only the network config is not enough.
2. **Land the Researcher's `checker_error` fix:** only docker launch exits 125, 126, or 127 count. Drop the "command not found" output grep. Not in `640f6751`.
3. **Do not classify a trial as infra `error` on a step/call count mismatch when the checker already produced a verdict.** Carbon `sanitize-git-repo` should have been a completed fail.
4. **Timeout ruling (Researcher):** when an agent was still actively working and ran out of time, that is a **task fail** and it stays in the denominator. Each trial should carry a `timed_out` flag so tables can show how many fails were timeouts. A timeout counts as infra only if no model call finished in the last 5 minutes before the cap (stuck proxy, upstream, or container). Use each task's own agent timeout from `task.toml` where it sets one, and 1800 s only where it doesn't. Both models get the same cap.

## What is in this folder

- `README.md`, `REPORT.md` (the PM's smoke report), `MANIFEST-large-files.txt`
- `notes/` — credential-scan verdict and redacted notes, early status, analysis text
- `smoke-a/` and `smoke-b/` — config, launcher, `smoke.log`, `run/plan.json`, `run/trials.jsonl`, summaries, `set_aside.json`, `verdicts.json`, `provider_blocked.json`, swap state (A only), and per-trial `cell.json`, `wire.jsonl`, `trace.jsonl`, `opencode-events.jsonl`, `checker-output.txt`, `checker-mode.txt`, `opencode-stderr.txt`, `provider_blocked.json`, and `model_refused.json`

Trial workspaces were not committed and remain on the VM under `~/pilot-smoke-640f/run` and `~/pilot-smoke-640f-w1/run`.

Transcripts and traces (`wire.jsonl`, `trace.jsonl`, `opencode-events.jsonl`, `checker-output.txt`, `opencode-stderr.txt`) plus `smoke.log`, `run-smoke.sh`, and `ps-before.txt` were passed through `python3 obench/scrub.py`. `python3 obench/scrub.py --check` on those files is CLEAN (exit 0), both with this machine's default identity and with `--user box --home /home/box --hostname thesis-h1-cpu`. Fixture credentials from the sanitize-git-repo task (`hf_…`, `ghp_…`, `AKIA…`) in those traces were replaced with scrubber placeholders.

## Files not in this commit

One file over 50 MiB, listed with size and sha256 in `MANIFEST-large-files.txt` and left on the VM:

- `smoke-a` / `run/trials/gemini-4-carbon/path-tracing/7a305881880f3a40/opencode-events.jsonl` (64,630,209 bytes, sha256 `26169f6566e7311275bc10725c868aab8e219ae6fcceb3fbbe666e6650f5aff4`)
