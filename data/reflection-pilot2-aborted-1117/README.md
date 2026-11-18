# ABORTED — reflection Pilot-2 (17 Nov 2026). INVALID. Do not pool.

**This run was ABORTED.**

**NONE of its trials are valid.**

**Do not pool these trials with later runs. Do not use them in tables, pass rates, the swap rule, credit assignment, or ideation.** Keep the folder only as a record of the harness bugs that stopped the run.

`rebuild_tables` will not pick this folder up on its own. On the #265 runner, `Runner.rebuild_tables()` only rewrites `summary.jsonl` and `verdicts.json` inside one explicit run directory, from that directory's `trials.jsonl`. `python -m obench.reflection.runner` requires `--out` to be outside `results/` and `data/`. `python -m obench.reflection.reclassify` takes an explicit `--run`. There is no repo convention that walks `data/` for reflection tables, and no marker file the runner honors. Placing this archive under `data/` is what keeps it out of those tools. Do not point `--out` or `--run` at this folder, and do not copy `trials.jsonl` into a later run directory.

## Run

| | |
|---|---|
| Host | `thesis-h1-cpu` (project `nyu-rdg-fy26-js11531-a68d`, zone `us-central1-a`) |
| Source on the VM | `~/pilot-2/` (launcher, `pilot.log`, config) and `~/pilot-2/run/` (copied read-only; the VM copy was not modified) |
| Head | [#265](https://github.com/sean-lai-sh/openbench/pull/265) at `80579940d8b9666131e2a771bcbaedb0d30efedd` |
| Models | `gemini-4-carbon` and `claude-opus-5-5`, mixed / interleaved |
| Workers | 8 (fixed for the run; recorded on every row) |
| Suite | repo pilot suite (`suite: "pilot"`) |
| Spend cap | $5,000 |
| OpenCode pin | `ba54cee55e18b47fb70badc84ae2cbac7c83d258` (the scrubbed `run-pilot.sh` shows this hash as `<REDACTED_HEX>`) |
| Started | 17 Nov 2026, 5:48:52 PM America/New_York (`2026-11-17T22:48:52+00:00`) |
| Last finished trial | 5:59:39 PM America/New_York (`2026-11-17T22:59:39+00:00`), about 11 minutes later |
| How it was stopped | The PM stopped the run after the harness bugs below. Nothing was running afterward; `~/pilot-1` was left untouched. |

Launcher, from the original `run-pilot.sh` (home paths and the pin hash are scrubbed in the committed copy):

```bash
python -m obench.reflection.runner \
  --config <HOME>/pilot-2/config.json \
  --out <HOME>/pilot-2/run \
  --cell \
  --opencode <HOME>/h1/opencode-src/bin/ba54cee55e18b47fb70badc84ae2cbac7c83d258/opencode \
  --use-image-tag \
  --workers 8
```

## Verified counts (from `run/trials.jsonl`)

These match the numbers reported when the run was stopped, with the notes below.

| | Carbon (`gemini-4-carbon`) | Opus (`claude-opus-5-5`) | Total |
|---|---:|---:|---:|
| Rows in `trials.jsonl` | 24 | 24 | **48** |
| `status=completed` | 12 | 24 | 36 |
| `status=provider_blocked` | 12 | 0 | 12 |
| Passes | **1** (`path-tracing` trial `f08eb8932b94a83d`) | **0** | 1 |
| Cost (USD) | 4.3081 | 2.9864 | **7.2944** (reported as **$7.29**) |

Other checks that also match:

- Every row has `code_commit=80579940d8b9666131e2a771bcbaedb0d30efedd`, `workers=8`, `run_id=pilot-2`.
- No `retried_4xx` entries; no 4xx responses.
- All 86 Opus main steps have `thinking_tokens_status=reported` (per-row field is a `{"reported": N}` count; the 24 Opus rows sum to 86). Carbon completed trials contribute 50 reported thinking-token steps; the 12 blocked Carbon trials have `thinking_tokens_status=null`.
- The 11 Carbon blocks on `dna-insert` (3), `dna-assembly` (3), `extract-elf` (2), and `model-extraction-relu-logits` (3) finished in 6.3–14.0 s. Most had `route_counts.model_calls=1`. Three `model-extraction-relu-logits` blocks have `model_calls=0` and `provider_blocked.call_index=1`.
- The 12th Carbon block is `path-tracing` trial `a61b77d6d9f70906`: `provider_blocked` with `promptFeedback` `blockReason=SAFETY`, 276.8 s in, after 4 model calls. The other Carbon `path-tracing` trial passed. Classification is per trial. This is not a 5th blocked task.

Notes versus the 48-trial figure:

- There are **53** trial directories under `run/trials/`, each with a `wire.jsonl`. 48 of them have a `cell.json` and a row in `trials.jsonl`. The other five were in flight when the run was stopped and have no row: `claude-opus-5-5/query-optimize/382c45e72aa51d6c`, `claude-opus-5-5/sanitize-git-repo/ec2f89df77852c20`, `gemini-4-carbon/adaptive-rejection-sampler/172f80ec245b70fd`, `gemini-4-carbon/adaptive-rejection-sampler/afb7fdd2802ced2a`, and `gemini-4-carbon/path-tracing/75def32e921da146`. They are kept here as part of the record and are also invalid.
- This run predates the `model_refused` and `agent_exit_pending_tool` labels. Opus refusals and OpenCode pending-tool exits are still recorded as `status=completed` fails in `trials.jsonl`. The rulings below say how they should have been labeled. Do not treat those rows as task fails.

## The 6 harness bugs

1. **The trial workspace is bind-mounted over the image's `/app`, so the agent sees an empty `/app`.** `query-optimize` lost its `.sql` file and `oewn.sqlite`; `corewars` lost `warriors/`; `sanitize-git-repo` (`/app/dclm`) is likely affected. The checker still sees the files, so these look like ordinary fails.

2. **Some checkers run agent code on the VM host instead of in the container.** `model-extraction-relu-logits` ran `steal.py` on the host and failed on `/app/stolen_A1.npy`. This is a sandbox escape, and it makes every trial of that task fail.

3. **OpenCode exits 0 with a tool call still pending.** Seen on `adaptive-rejection-sampler` 3/3, `path-tracing` 2/2, and `corewars` 2/2, after 8 to 36 s. `pilot.log` shows proxy `ConnectionResetError`s. Whether concurrency causes it is unknown. Per the Researcher this is now labeled `agent_exit_pending_tool`, an infra failure, never a task fail. A workers=1 rerun of a couple of these tasks is required before the next full start.

4. **Opus `stop_reason: refusal` on `dna-insert` 3/3 and `dna-assembly` 3/3 was recorded as completed fails.** The Researcher's ruling: give these their own status, `model_refused`, separate from `provider_blocked`. Like `provider_blocked`, they are neither a pass nor a fail, are left out of the pass-rate denominator, do not count toward the swap rule, and are not sent to credit assignment or ideation. Report them per task with the step they happened on. A mid-trial Gemini `finishReason: SAFETY` is also `model_refused`.

5. **Carbon `path-tracing` was blocked once at 277 s (276.8 s in the row) while the other trial passed.** Classification is always per trial, never per task. This trial is `provider_blocked` because the last call carried `blockReason`; otherwise it would be `model_refused`. `path-tracing` is not a 5th blocked task. Tables should show blocked and refused counts per task and model. Because excluding trials could inflate pass rates if blocks happen on harder runs, the writeup also gives a check that counts every blocked or refused trial as a fail.

6. **The container mounts `/home/box/h1/opencode-src` read-only, so the host's OpenCode worktrees are visible via `find /`.**

## What is in this folder

- `run-pilot.sh`, `config.json`, `preflight.json`, `preflight.err`, `pilot.log`, `summary-at-stop.txt`
- `run/plan.json`, `run/trials.jsonl`, `run/swaps/`
- Per-trial `cell.json` (48), `wire.jsonl` (53), `trace.jsonl`, `opencode-events.jsonl`, `checker-output.txt`, `provider_blocked.json`, and workspaces

Transcripts and traces (`pilot.log`, `wire.jsonl`, `trace.jsonl`, `opencode-events.jsonl`, `checker-output.txt`) and `run-pilot.sh` were passed through `python3 obench/scrub.py`. `python3 obench/scrub.py --check` on those files is CLEAN (exit 0), both with this machine's default identity and with `--user box --home /home/box --hostname thesis-h1-cpu`. Fixture credentials in sanitize-git-repo workspace text (`hf_…`, `ghp_…`, `AKIA…`) were replaced with the scrubber placeholders so they cannot trip GitHub push protection. Those workspace files are not traces; they were not run through the full hex/base64 scrub.

Git cannot track a nested `.git`. The three `sanitize-git-repo` workspace git dirs are stored here as `workspace/dot-git/`. The original path was `workspace/.git/`.

## Files not in this commit

**Over 50 MiB**, listed with size and sha256 in `MANIFEST-large-files.txt`, left on the VM under `~/pilot-2/`:

- Three identical 53,764,437-byte git pack files in the `sanitize-git-repo` workspaces (sha256 `658d4bac17bcd01c2494045664639c044defbcdd115e61bd5b90047f79bdcc54`).

**Unreadable on the VM** (mode `600`, owner `root:root`, 35 bytes each). They were not copied, and the VM was not modified to make them readable:

- `run/trials/claude-opus-5-5/model-extraction-relu-logits/{7974451440dc9d86,1d43b7edd24e2bb4,42f21826dba82ae3}/workspace/.ruff_cache/0.12.5/7572410818329038002`
