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
| `plan.json` | Config (including `suite_label` and `workers`), `host_cpus`, cutoff, `code` (commit, branch, dirty), and the preflight cost estimate. Resuming a run directory with a different `suite`, `suite_label`, `models`, `patch_id`, `n_trials` or `workers` is refused, so populations are never pooled in one directory. `workers` (`--workers N`, one fixed value for the run and both models; 6-8 on the 16-CPU VM): each trial is its own container and proxy, trials are interleaved across models (trial index, then slot, then model), swaps are applied per model after each round so they are the same at any N, and the spend cap counts the estimates of running trials. |
| `provider_blocked.json` | Per model, per task: provider-blocked trials (`trials_blocked` of `trials`), the raw `block_reasons` counts and `block_reason_messages`, and how many were `inferred` |
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
| `status` | string | `completed`, `error`, `timeout`, `route_truncated`, `harness_aborted` (OpenCode ended the run with a tool call still pending; e.g. `opencode run` auto-rejects permission requests), `checker_error` (the checker itself could not run), `model_refused` (the model declined: Anthropic `stop_reason: "refusal"`; kept apart from pass/fail and infra, see the summary row), `provider_blocked` (the provider refused the prompt itself, e.g. Gemini `promptFeedback.blockReason: SAFETY`: neither pass nor fail, see the summary row), `upstream_4xx` (a main call came back 4xx and no main call after it succeeded: the 4xx ended or broke the trial; `wire_proxy.classify_4xx`). A 4xx that OpenCode retried and recovered from does not change the status; it is counted in `retried_4xx`. An executor crash is recorded as `error`, never skipped. `route_truncated` means the last model call ended with finish reason stop, no tool call and no text. Both it and `upstream_4xx` are infrastructure failures, not task fails. Every status other than `completed` has `passed: null`; all but `provider_blocked` and `model_refused` count in `errors`, so the cell stays `incomplete` until it has N completed trials. |
| `passed` | bool\|null | Checker verdict; null unless `completed` |
| `checker_exit`, `steps` | int\|null | |
| `cost_usd` | number\|null | From the wire records (`vertex_models.cost_usd`) |
| `price_verified` | bool | False for Carbon and gpt-oss (unverified list prices) |
| `thinking_tokens` | int\|null | Sum of `usage.thinking_tokens` (response usage) over steps |
| `thinking_flags` | array | E.g. `reported_zero_text_present` (gpt-oss) |
| `served_models`, `wrong_model_served` | array | Models the provider served. Any not matching `vertex_id` lands in `wrong_model_served`. |
| `route_counts` | object\|null | `{model_calls, tool_call_turns, route_repairs, unknown_recipient_calls}` from the trial's wire records (`wire_proxy.route_repair_counts`): main calls answered, those that handed OpenCode a tool call, and those whose tool call the proxy rebuilt from gpt-oss text (`route_repair`). `null` when the executor produced no wire counts. |
| `suite_label` | string\|null | The run's label (`RunConfig.suite_label`), e.g. `repo pilot suite`. Each label fixes the allowed suites; `repo pilot suite` allows `pilot` only and refuses tasks imported by `obench.taskimport` (their `task.toml` has `docker_image_id_at_import`). Never pool rows with different labels. |
| `code_commit`, `code_branch`, `code_dirty` | string\|bool\|null | The checkout the runner ran from (`git rev-parse HEAD`, branch, uncommitted changes) |
| `retried_4xx` | object | 4xx calls the trial recovered from, by status code (e.g. `{"429": 2}`), plus side-call 4xx: a covariate, not a failure |
| `image_ref`, `image_id` | string\|null | The image ref the agent container ran and its local image id (`docker image inspect .Id`) |
| `image_matches_pin` | bool\|null | `true` when the task's pinned ref or `docker_image_id` ran; `false` when `--use-image-tag` ran `docker_image_tag` instead (the 4 tb-mid tasks); `null` when the task pins nothing (checker or default image) |
| `thinking_setting` | object\|null | The exact thinking setting the proxy sent on this trial's requests (`VertexModel.thinking_sent`, e.g. Opus `{"thinking": {"type": "adaptive", "display": "summarized"}, "output_config": {"effort": "high"}}`) |
| `thinking_tokens_status` | object\|null | Steps by `usage.thinking_tokens_status`, e.g. `{"reported": 3, "unreported": 1}`. An `unreported` step's count is null and is **not** 0: `thinking_tokens` sums reported steps only. |
| `thinking_tokens_per_step` | array\|null | `usage.thinking_tokens` for each trace step, in order (`null` entries where usage reported none) |
| `trace`, `wire`, `trial_dir` | string\|null | Relative pointers |
| `started_at`, `finished_at` | string | ISO-8601 UTC |
| `provider_blocked` | object\|null | Raw `{blockReason, blockReasonMessage, safetyRatings}` plus `call_index`, `calls_blocked` for a `provider_blocked` trial (`inferred: true` when reclassified from records that predate the field) |
| `model_refused` | object\|null | `{stop_reason, stop_details, call_index, calls_refused, last_call_refused}` for a `model_refused` trial (`checker_exit` is still recorded) |
| `harness_abort` | object\|null | For `harness_aborted`: `{last_finish, pending_tools, permission_rejected, stream_errors}` |
| `workers` | int | The run's fixed worker count |
| `wall_seconds`, `host_load` | number, object | Trial wall time, and `{start, end, cpus}`: the host's 1/5/15-minute load average when the trial started and ended, so contention-driven timeouts are visible |
| `error` | string\|null | |

## Summary row (`openbench.reflection.summary/v1`)

| Field | Meaning |
|---|---|
| `task`, `model`, `patch_id` | The group. `gpt-oss-120b-medium` ("gpt-oss at medium", opt-in) is its own model key, so it is never pooled with `gpt-oss-120b` (effort high). |
| `planned`, `trials`, `completed`, `passes`, `fails`, `errors` | Counts |
| `route_truncated`, `upstream_4xx` | How many of `errors` were `route_truncated` / `upstream_4xx` trials |
| `provider_blocked` | Trials whose prompt the provider blocked (**not** in `errors`). Researcher ruling 2026-11-17: neither pass nor fail and excluded from the model's pass rate. A cell with any blocked trial gets verdict `excluded` once all its trials are in. It is never swapped, never sent to credit assignment (Methods A/B) or ideation, and is listed in `provider_blocked.json` and in `verdicts.json` (`excluded`, `provider_blocked`). |
| `model_refused`, `model_refused_checker_passes` | Trials where the model declined (**not** in `errors`), and how many of them the checker would still pass. A cell with any refusal gets verdict `model_refused` once all its trials are in (no swap). How refusals count is the Researcher's call; the rows keep everything needed to recount them. |
| `harness_aborted`, `checker_error` | How many of `errors` were these infrastructure statuses |
| `workers` | The worker count(s) the group's trials ran under |
| `retried_4xx` | Sum of the trials' `retried_4xx` by status code |
| `image_ids`, `image_matches_pin` | Every image id the group ran; `false` if any trial ran an image that doesn't match its pin, `true` if all matched, `null` if no pin. `verdicts.json` lists such tasks per model as `image_matches_pin_false`. |
| `suite_label`, `code_commits` | The run label, and every commit the group's trials ran from |
| `model_calls`, `tool_call_turns`, `route_repairs` | Sums of the trials' `route_counts`. Always 0 repairs for Carbon and Opus, which are never rewritten. |
| `unknown_recipient_calls` | **Model errors:** gpt-oss tool calls to a tool we never offered (e.g. `repo_browser.print_tree`). They are never remapped onto our tools; OpenCode answers them with its `invalid` tool's error. Included in `route_repairs`. Every rebuilt call is also logged per cell by the executor (`<model>/<task>/route_repairs.jsonl`). |
| `route_repair_share` | `route_repairs / tool_call_turns`: the share of gpt-oss's tool calls that exist only because of our parser (`null` with no tool calls) |
| `trials_with_route_repair`, `passes_with_route_repair` | Trials with at least one repair, and how many of those passed: the passes that depend on the parser |
| `trials_without_route_counts` | Trials with no wire counts (crashes), left out of the sums |
| `pass_rate` | `passes / completed` |
| `cutoff`, `verdict` | `pass` iff `completed == planned` and `passes / completed >= cutoff` (exact; 27/30 at 0.90). `incomplete` when fewer than `planned` trials completed. |
| `spend_usd`, `spend_complete` | Sum of trial costs. `spend_complete` is false if any trial had no cost. |
| `thinking_tokens_total`, `thinking_tokens_reported_trials` | Usage thinking tokens summed over trials that reported them |
| `thinking_tokens_status` | Steps by thinking-count status, summed over the group's trials. Any `unreported` means `thinking_tokens_total` is a lower bound, not a measurement of zero. |
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

- `FixtureExecutor`: offline dry runs and tests.
- **Containerized cell executor: next step, needed before the pilot (SEA-111).** One task-image container per trial runs the pinned OpenCode against the `wire_proxy` route, with `--format json --thinking`, then the task checker. It builds `trace.jsonl` with `trace.build_trace` and returns cost, thinking tokens and served models from the wire records. It needs the VM (Docker and the task images) to build and prove.
