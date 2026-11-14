# Reflection-loop runner tables (SEA-107)

Writer: `obench/reflection/runner.py` (`Runner`). Tests:
`obench/tests/test_reflection_runner.py`. One run directory per run. All paths
inside rows are relative to it, so the tables can be committed after scrubbing.

## Config (`RunConfig`, JSON)

| Key | Default | Meaning |
|---|---|---|
| `run_id` | required | Name of the run. It is part of every trial id. |
| `suite` | required | `obench/hardsuite/suites/<suite>.toml`. Its `pool` file supplies harder swaps. |
| `models` | required | Any of `gemini-4-carbon`, `claude-opus-5-5`, `gpt-oss-120b`. Other names fail (`vertex_models.resolve`). |
| `n_trials` | `N_TRIALS = 30` | Trials per task per model |
| `spend_cap_usd` | none | The run stops before a trial that would pass it (`state: capped`) |
| `alert_thresholds_usd` | `[5000, 10000, 15000]` | The run pauses when spend crosses one (`state: alert`). Resume with `acknowledge_alerts`. |
| `max_rounds` | 3 | Swap rounds. A swapped-in task runs in the next round. |
| `patch_id`, `patch` | none | An ideation alternative (SEA-110). Patch runs never swap the suite. |
| `tasks` | all suite tasks | Restrict to these suite tasks (ideation, dry runs) |

The pass cutoff is **not** a runner setting. It is `obench.hardsuite.config.PASS_CUTOFF`
(`pass_cutoff()`), recorded in `plan.json`, `summary.jsonl` and `verdicts.json`.

## Files

| File | What |
|---|---|
| `plan.json` | Config, cutoff, and the preflight cost estimate |
| `trials.jsonl` | One `openbench.reflection.trial/v1` row per trial (append-only; a rerun skips ids already present) |
| `summary.jsonl` | One `openbench.reflection.summary/v1` row per (task, model, patch) |
| `verdicts.json` | Per model: `pass` / `fail` / `incomplete` tasks, and its current suite after swaps |
| `swaps/<model>.json` | That model's swap state (`obench.hardsuite.swap`) |
| `status.json` | `done`, `capped` or `alert`, with spend so far |
| `trials/<model>/<task>/<trial_id>/` | Executor output (`trace.jsonl`, `wire.jsonl`, events, checker output) |

## Trial row (`openbench.reflection.trial/v1`)

| Field | Type | Meaning |
|---|---|---|
| `schema`, `run_id`, `trial_id` | string | `trial_id = sha256([run_id, task, model, patch_id, index])[:16]`: deterministic |
| `task`, `bench`, `bench_commit` | string | The task and its upstream bench snapshot |
| `model`, `vertex_id` | string | The reflection model and its Vertex ID |
| `trial_index` | int | 0..n_trials-1 |
| `patch_id` | string\|null | Null for baseline rows |
| `status` | string | `completed`, `error` or `timeout`. An executor crash is recorded as `error`, never skipped. |
| `passed` | bool\|null | Checker verdict; null unless `completed` |
| `checker_exit`, `steps` | int\|null | |
| `cost_usd` | number\|null | From the wire records (`vertex_models.cost_usd`) |
| `price_verified` | bool | False for Carbon and gpt-oss (unverified list prices) |
| `thinking_tokens` | int\|null | Sum of `usage.thinking_tokens` (response usage) over steps |
| `thinking_flags` | array | E.g. `reported_zero_text_present` (gpt-oss) |
| `served_models`, `wrong_model_served` | array | Models the provider served. Any not matching `vertex_id` lands in `wrong_model_served`. |
| `trace`, `wire`, `trial_dir` | string\|null | Relative pointers |
| `started_at`, `finished_at` | string | ISO-8601 UTC |
| `error` | string\|null | |

## Summary row (`openbench.reflection.summary/v1`)

| Field | Meaning |
|---|---|
| `task`, `model`, `patch_id` | The group |
| `planned`, `trials`, `completed`, `passes`, `fails`, `errors` | Counts |
| `pass_rate` | `passes / completed` |
| `cutoff`, `verdict` | `pass` iff `completed == planned` and `passes / completed >= cutoff` (exact; 27/30 at 0.90). `incomplete` when fewer than `planned` trials completed. |
| `spend_usd`, `spend_complete` | Sum of trial costs. `spend_complete` is false if any trial had no cost. |
| `thinking_tokens_total`, `thinking_tokens_reported_trials` | Usage thinking tokens summed over trials that reported them |
| `thinking_flags`, `wrong_model_trials` | Carried up from the trial rows |
| `traces` | Glob of the group's trace files |

## Verdict and swaps

After each round:
1. The summary is rewritten.
2. Each model's completed baseline groups go through `obench.hardsuite.swap.apply_results` **for that model only**.
3. Swapped-in tasks run in the next round, up to `max_rounds`.

So a model's suite keeps its planned size. If the pool runs out, `PoolExhausted` stops the run loudly rather than shrinking the suite.

## Spend

- `preflight()` gives `round_one_usd` (tasks × models × N × the executor's per-trial estimate) and `worst_case_usd` (× `max_rounds`), checked against `spend_cap_usd`.
- During the run, spend is the sum of logged trial costs. Every trial checks the cap and the alert thresholds before it starts.

## Executors

`Executor` is the interface: `estimate_cost_usd(model)` and
`run_trial(spec, run_dir) -> TrialResult`.

- `FixtureExecutor` (`--fixture`): offline dry runs and tests.
- `CellExecutor` (`--cell`, `cell_executor.py`): one container of the
  task's image per trial.
  1. The task workspace is mounted at WORKDIR.
  2. The pinned OpenCode runs (`--format json --thinking`) against a
     per-trial recording proxy, bound to the Docker bridge gateway and
     carrying the ideation patch if there is one. Provider API hosts are
     sinkholed.
  3. The task's `checker.sh` runs on the workspace.
  4. The trace is built from the events and wire records.

  The agent's image comes from `task.toml` `docker_image` (with
  `docker_image_id` checked), else the pinned image named in `checker.sh`,
  else `--default-image` (`h1-env:1027-strace`, for openbench-tb-hard). Each
  trial's `cell.json` records which.

  A trace that can't be built makes the trial an `error`, so the group is
  `incomplete`: missing traces never pass silently. A timeout is `timeout`.

  Per-trial preflight estimates are provisional (`DEFAULT_ESTIMATES_USD`:
  Carbon $1.50, Opus $2.00, gpt-oss $0.10). Calibrate them from the smokes
  with `--estimates`.

  Tested with a fake Docker that plays the container: real proxy, fake Vertex,
  real trace and checker. **Untested** against real images until the VM run.
