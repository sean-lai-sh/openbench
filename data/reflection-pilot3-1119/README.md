# Reflection pilot-3 (run id `pilot-3`, started 2026-11-19)

Scrubbed, slim archive of the reflection-loop pilot-3 run: Opus (`claude-opus-5-5`) and
Carbon (`gemini-4-carbon`) on the repo pilot suite, n=30 per cell, swap cutoff 0.9.

- Host: `thesis-h1-cpu` (GCP VM, us-central1-a, 16 vCPU, 8 workers).
- Rounds 1–2 ran at code commit `422e818a` (Nov 19). The infra-retry resume ran at `6dc1999f`
  (Nov 24–25, #271). Bench commit is `2fd12b88` for every row.
- Total spend: $786.59 (`status.json`, state `done`).

## Results must be split by row `code_commit`

`plan.json` still says `code.commit = 422e818ad5b8cfec3c88bf0039f519818f959b27`. That is **stale**: it
was written at the first start and was not rewritten on resume. 104 rows were produced at
`6dc1999f272a3db0bbdfa7fad04a8d93d91b03a7`. Always split and label results by each row's own
`code_commit` field, never by `plan.json`.

| code_commit | rows | Opus | Carbon |
|---|---|---|---|
| 422e818a | 630 | 330 | 300 |
| 6dc1999f | 104 | 43 | 61 |
| total | 734 | 373 | 361 |

## Files

| File | What it is |
|---|---|
| `trials.jsonl` | Every trial row from both commits, as the runner recorded it (734 rows). |
| `trials-422e818a.jsonl` | Rows with `code_commit` 422e818a (630). |
| `trials-6dc1999f.jsonl` | Rows with `code_commit` 6dc1999f (104). |
| `summary.jsonl` | Per-cell (model × task) summary written by the runner at the end (23 lines). |
| `verdicts.json` | Final per-model pass / fail / excluded / refused verdicts (written at 6dc1999f). |
| `set_aside.json` | Per-cell `provider_blocked` / `model_refused` counts and the set-aside rule. |
| `provider_blocked.json` | Per-cell provider block reasons (Carbon safety blocks). |
| `swaps/claude-opus-5-5.json` | Opus hard-swap state: path-tracing → polyglot-c-py (30/30, Nov 19), winning-avg-corewars → video-processing (27/30). |
| `swaps/gemini-4-carbon.json` | Carbon hard-swap state: polyglot-rust-c → video-processing (30/30). |
| `plan.json` | Run plan and config at first start (commit field stale, see above). |
| `status.json` | Final runner status (`done`, total spend). |
| `oracle.jsonl` | Current oracle (reference-solution) check at 6dc1999f. |
| `oracle-846caf45.jsonl` | Superseded oracle row from 846caf45, kept for the record. |
| `isolation-6dc1999f.json` | Network-isolation probe (metadata endpoint blocked, proxy reachable) at 6dc1999f. |
| `relabel.csv` | Label overrides for 13 Opus winning-avg-corewars rows (below). |

`oracle*.jsonl` point to `oracle-work/...` stdout/stderr tails that are not in this bundle.

## Relabel table (`relabel.csv`): raw rows are untouched

13 Opus `winning-avg-corewars` rows carry `status: agent_exit_pending_tool` (10 at 422e818a,
3 at 6dc1999f on slots 3, 4 and 18). Each ended on an HTTP 400 from OpenCode's **compaction** side request (no tools;
system prompt identical to `packages/opencode/src/agent/prompt/compaction.txt` at OpenCode pin
`ba54cee55e18b47fb70badc84ae2cbac7c83d258`, first line "You are a helpful AI assistant tasked with
summarizing conversations.") that replayed a thinking block whose signature was bound to
the main conversation: "Invalid `signature` in `thinking` block. The block is bound to a different
conversation…". `pending_tools` is `["bash"]` and `permission_rejected` is `[]` in every case, so these
were not permission rejections.

The rows in `trials.jsonl` are **not** rewritten. `relabel.csv` maps each `trial_id` to
`relabeled_status = side_thinking_signature` and `env_cause = vertex_thinking_signature`, with the
evidence (`agent_exit.json` path, `pending_tools`, `permission_rejected`, the 400 call index/time,
`side_kind = compaction`, and the message). The analysis reads labels from `relabel.csv`. They remain infra (not task fails). The fix is
#272; Opus rows after that fix are a separate condition, labeled by commit.

`recorded_checker_exit` / `recorded_checker_result_line` are what the runner's checker already wrote to
each trial's `checker-output.txt` at trial time (the row's `passed` is null because the status is infra).
They were not re-run for this bundle.

## Reporting rules

- `sanitize-git-repo` is **excluded from pass rates** (both models).
- `provider_blocked` and `model_refused` trials are neither pass nor fail: out of the denominator and
  the swap rule; `*_all_fail` fields give the sensitivity check counting them as fails.

## Opus winning-avg-corewars is compaction-censored

This cell is **not clean evidence** that Opus solves corewars. Report it with three numbers:

| Reading | Passes | How |
|---|---|---|
| Retried (verdict) | 27/30 | Each of the 10 affected slots re-run until it settled. |
| First attempt | 19/30 | The 18 passes on the 20 unaffected slots plus 1/10 for the recorded checker result on the 10 first attempts (only slot 4, `21c6d46e24a1662c`, wrote `my_warrior.red` and scored 1.0). |
| Sensitivity | 18/30 | The 18 passes on the 20 unaffected slots; all 10 affected slots counted as fails. |

Why: OpenCode runs compaction partway through a task, when the context fills. At 422e818a and 6dc1999f
that compaction request replayed a main-conversation thinking block and got an HTTP 400, which ended the
trial while the agent was still working (9 of the 10 first attempts had not yet written the answer
file). Re-running until a slot settled therefore favored attempts that never needed compaction, so
27/30 is biased upward, and 1/10 is not a clean task-fail rate either, because the harness cut those
agents off.

The hard swap (winning-avg-corewars → video-processing) **stands**: the swap rule was applied as written.
The corewars cell here is compaction-censored; the uncensored Opus corewars result is `data/reflection-corewars-b595f7d7-1125/` (28/30, Wilson [0.787, 0.982]), reported separately and not pooled.

**Other cells are unaffected.** Every Opus wire record in pilot-3 (373 trials, both commits, all 11
tasks) was matched against OpenCode's side prompts at the pin. The only compaction calls are the 13 in
the corewars trials listed in `relabel.csv`; all 13 got the 400. No Opus trial outside corewars
compacted, so the other Opus cells are unaffected. (Every Opus trial also made title calls, which match
`title.txt` exactly; none got a 400.) Carbon does not use the Anthropic route, so it is not affected.

## What is not here

The full per-trial dirs (`trials/<model>/<task>/<trial_id>/`: `wire.jsonl`, `trace.jsonl`,
`opencode-events.jsonl`, `cell.json`, `agent_exit.json`, `checker-output.txt`, `workspace/`, ~17 GB)
stay on the VM disk at `~/pilot-3/run/trials/`. Every `trial_dir` in `trials.jsonl` is relative to `~/pilot-3/run/`.

## Scrubbing

Checked with `obench/scrub.py` rules (the VM username and its home path, the VM host name) plus extra patterns
(AIza, ya29., Bearer, sk-, private keys, IPv4, home paths, GCP project id). No emails, keys, tokens,
usernames or home paths were found. Remaining flags are not secrets and were kept: git commit SHAs and
sha256 image digests (hex-blob/base64-blob flags), `0.0.0.0` / `169.254.169.254` (isolation rules), and
the short VM name `thesis-h1-cpu`. The full internal host name (which contained the GCP project id)
was replaced with `thesis-h1-cpu` in `plan.json`, `oracle.jsonl`, `oracle-846caf45.jsonl` and this README.
