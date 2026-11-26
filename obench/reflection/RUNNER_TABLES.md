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
| `fixed_tasks` | false | Run exactly `tasks` (suite or pool tasks) and never swap. Ideation's selection, confirmation and fresh-baseline arms use it. |
| `smoke_compaction` | false | Opt-in smoke profile. Default off. When true, the cell executor sets OpenCode's model `limit.context` to 72000. Opus output limit is 32000 and `limit.input` is unset, so the usable window is 40000 (`72000 - min(32000, 32000)`). OpenCode stays the pinned binary; this is its own config field, not a source patch. `--smoke-compaction` and `OBENCH_SMOKE_COMPACTION=1` turn it on. Recorded here and as `smoke_compaction` on `plan.json` and every trial row, so these rows are not pooled with a normal run. A resume refuses a different value (a plan from before the field counts as false). |

The pass cutoff is **not** a runner setting. It is `obench.hardsuite.config.PASS_CUTOFF`
(`pass_cutoff()`), recorded in `plan.json`, `summary.jsonl` and `verdicts.json`.

## Files

| File | What |
|---|---|
| `plan.json` | `isolation`: the executor's live metadata probe (a container on the trial network must fail to reach 169.254.169.254:80 and metadata.google.internal:80; if it connects, the run does not start). Config (including `suite_label` and `workers`), `host_cpus`, cutoff, `code` (commit, branch, dirty), `host` (the VM hostname), and the preflight cost estimate. Resuming a run directory with a different `suite`, `suite_label`, `models`, `patch_id`, `n_trials` or `workers` is refused, so populations are never pooled in one directory. A resume whose git commit or `host` differs from this file is also refused (`--allow-plan-mismatch` overrides that check only). A plan written before `host` existed gets the current host filled in. `workers` (`--workers N`, one fixed value for the run and both models; 6-8 on the 16-CPU VM): each trial is its own container and proxy, trials are interleaved across models (trial index, then slot, then model), swaps are applied per model after each round so they are the same at any N, and the spend cap counts the estimates of running trials. Omitting `--workers` on resume keeps the value recorded here. |
| `set_aside.json` | Per model and task: `provider_blocked` and `model_refused` counts, the refusals (trial, stop reason, step, details), pass rate and verdict over completed trials, and the all-fail sensitivity check |
| `provider_blocked.json` | Per model, per task: provider-blocked trials (`trials_blocked` of `trials`), the raw `block_reasons` counts and `block_reason_messages`, and how many were `inferred` |
| `trials.jsonl` | One `openbench.reflection.trial/v1` row per attempt (append-only). A resume skips trial ids already present. `--retry-infra` appends a new row for an infrastructure-error slot (`retry_of` is the original trial id) and does not rewrite the original row. At most 3 re-runs per slot; the cell then stays `incomplete` with `incomplete_reason` |
| `summary.jsonl` | One `openbench.reflection.summary/v1` row per (task, model, patch) |
| `verdicts.json` | Per model: `pass` / `fail` / `incomplete` tasks, and its current suite after swaps |
| `swaps/<model>.json` | That model's swap state (`obench.hardsuite.swap`) |
| `status.json` | `done`, `capped` or `alert`, with spend so far |
| `trials/<model>/<task>/<trial_id>/` | Executor output (`trace.jsonl`, `wire.jsonl`, events, checker output) |

## Trial row (`openbench.reflection.trial/v1`)

| Field | Type | Meaning |
|---|---|---|
| `schema`, `run_id`, `trial_id` | string | `trial_id = sha256([run_id, task, model, patch_id, index])[:16]` for the original attempt. A re-run appends the attempt number to that list, so it is a new id |
| `task`, `bench`, `bench_commit` | string | The task and its upstream bench snapshot |
| `model`, `vertex_id` | string | The reflection model and its Vertex ID |
| `trial_index` | int | 0..n_trials-1 |
| `patch_id` | string\|null | Null for baseline rows |
| `status` | string | `completed`, `error`, `timeout`, `route_truncated`, `agent_exit_pending_tool` (OpenCode exited 0 with a tool call still pending; e.g. `opencode run` auto-rejects permission requests: infrastructure, never a task fail), `side_thinking_signature` (the last call was a side request — title, summary, or compaction — rejected with the thinking-block signature 400, and the last step still shows a tool call; the tool had already finished, so this is not `agent_exit_pending_tool`; infrastructure, `env_cause=vertex_thinking_signature`, never a task fail), `post_compaction_signature` (a main turn after a side call in the same trial was rejected with that signature 400 and no later main call succeeded; the side response's thinking block was replayed; infrastructure, same `env_cause`; this outranks `upstream_4xx` and `agent_exit_pending_tool`. If the last call is the side signature 400 and the last step still shows a tool call, the status stays `side_thinking_signature`), `checker_error` (the checker itself could not run), `provider_blocked` (the trial's last answered call had Gemini `promptFeedback.blockReason`), `model_refused` (otherwise, any call refused or stopped for safety: Anthropic `stop_reason: "refusal"` or Gemini `finishReason: SAFETY`; both are set aside, see the summary row), `upstream_4xx` (a main call came back 4xx and no main call after it succeeded: the 4xx ended or broke the trial; `wire_proxy.classify_4xx`). A 4xx that OpenCode retried and recovered from does not change the status; it is counted in `retried_4xx`. An executor crash is recorded as `error`, never skipped. `route_truncated` means the last model call ended with finish reason stop, no tool call and no text. `route_truncated`, `upstream_4xx`, `side_thinking_signature`, and `post_compaction_signature` are infrastructure failures, not task fails. Signature precedence is `side_thinking_signature`, then `post_compaction_signature`, then `upstream_4xx`, then `agent_exit_pending_tool`. A main-turn signature 400 with no earlier side call stays `upstream_4xx`. Every status other than `completed` has `passed: null`; all but `provider_blocked` and `model_refused` count in `errors`. A cell is `incomplete` until every trial is either completed or set aside. The pass/fail formula is unchanged. |
| `passed` | bool\|null | Checker verdict; null unless `completed` |
| `checker_exit` | int\|null | Checker exit code |
| `steps` | int\|null | Main-agent calls that returned 200. One trace row each. Compaction summary steps are not included. Null when the trace could not be built. |
| `cost_usd` | number\|null | From the wire records (`vertex_models.cost_usd`) |
| `runtime_measured_s`, `runtime_golden_s`, `runtime_ratio` | number\|null | From the checker's own output when it prints query-optimize's medians (`solution.median_s`, `golden.median_s`). `runtime_ratio` is measured / golden. All three are null when the checker does not report both medians. The runner does not re-time the query |
| `price_verified` | bool | False for Carbon and gpt-oss (unverified list prices) |
| `compaction_steps` | int\|null | Session steps that are the compaction summary: the step immediately before OpenCode's synthetic continue text. Not included in `steps`. 0 when the trace was built and the trial did not compact. Null when the trace was not built. |
| `summary_steps` | int\|null | Session steps attributed to the summary agent, when they can be distinguished from compaction steps. Title and summary side calls do not emit a session step. 0 when none are distinguished. Null when the trace was not built. |
| `synthetic_continue_messages` | int\|null | OpenCode's synthetic "Continue if you have next steps, or stop and ask for clarification if…" text events. Input, not a step. One per compaction in the streams that compact. Null when the trace was not built. |
| `thinking_tokens` | int\|null | Sum of `usage.thinking_tokens` (response usage) over main steps only. Compaction-step thinking is not included. |
| `compaction_thinking_tokens` | int\|null | Provider thinking tokens of the compaction steps, summed from the compaction wire calls paired with those steps in `call_index` order. Null usage counts as 0. Never added to `thinking_tokens`. 0 when the trace was built and nothing was compacted. OpenCode's own `tokens.reasoning` on those steps is not this value. |
| `thinking_flags` | array | E.g. `reported_zero_text_present` (gpt-oss) |
| `served_models`, `wrong_model_served` | array | Models the provider served. Any not matching `vertex_id` lands in `wrong_model_served`. |
| `route_counts` | object\|null | `{model_calls, tool_call_turns, route_repairs, unknown_recipient_calls}` from the trial's wire records (`wire_proxy.route_repair_counts`): main calls answered, those that handed OpenCode a tool call, and those whose tool call the proxy rebuilt from gpt-oss text (`route_repair`). `null` when the executor produced no wire counts. |
| `suite_label` | string\|null | The run's label (`RunConfig.suite_label`), e.g. `repo pilot suite`. Each label fixes the allowed suites; `repo pilot suite` allows `pilot` only and refuses tasks imported by `obench.taskimport` (their `task.toml` has `docker_image_id_at_import`). Never pool rows with different labels. |
| `code_commit`, `code_branch`, `code_dirty` | string\|bool\|null | The checkout the runner ran from (`git rev-parse HEAD`, branch, uncommitted changes) |
| `retried_4xx` | object | 4xx calls the trial recovered from, by status code (e.g. `{"429": 2}`), plus side-call 4xx: a covariate, not a failure |
| `image_ref`, `image_id` | string\|null | The image ref the agent container ran and its local image id (`docker image inspect .Id`) |
| `image_matches_pin` | bool\|null | `true` when the task's pinned ref or `docker_image_id` ran; `false` when `--use-image-tag` ran `docker_image_tag` instead (the 4 tb-mid tasks); `null` when the task pins nothing (checker or default image) |
| `thinking_setting` | object\|null | The exact thinking setting the proxy sent on this trial's requests (`VertexModel.thinking_sent`, e.g. Opus `{"thinking": {"type": "adaptive", "display": "summarized"}, "output_config": {"effort": "high"}}`) |
| `thinking_tokens_status` | object\|null | Main steps by `usage.thinking_tokens_status`, e.g. `{"reported": 3, "unreported": 1}`. An `unreported` step's count is null and is **not** 0: `thinking_tokens` sums reported steps only. Non-null when the trace was built. |
| `thinking_tokens_per_step` | array\|null | `usage.thinking_tokens` for each trace step, in order (`null` entries where usage reported none) |
| `trace`, `wire`, `trial_dir` | string\|null | Relative pointers |
| `started_at`, `finished_at` | string | ISO-8601 UTC |
| `provider_blocked` | object\|null | Raw `{blockReason, blockReasonMessage, safetyRatings}` plus `call_index`, `calls_blocked` for a `provider_blocked` trial (`inferred: true` when reclassified from records that predate the field) |
| `model_refused` | object\|null | For `model_refused`: the first refusal `{stop_reason, stop_details, safety_ratings, call_index, step}`, plus `refusals` (every refused call, with its step) and `calls_refused`. `checker_exit` is still recorded. |
| `agent_exit` | object\|null | For `agent_exit_pending_tool`: `{last_finish, pending_tools, permission_rejected, stream_errors, opencode_exit}` |
| `env_cause` | string\|null | `vertex_thinking_signature` when `status` is `side_thinking_signature` or `post_compaction_signature`. Null otherwise. No other cause is assigned here |
| `signature_400s` | int | How many wire calls in this trial returned the thinking-block signature 400 (`thinking_signature_reject` on the wire record) |
| `side_kinds` | object | Counts of side requests by kind: `title`, `summary`, `compaction`, `unknown`. Empty when the trial made no side call |
| `side_signature` | object\|null | For `side_thinking_signature`: the terminating side call `{call_index, side_kind, status, thinking_block_binding, anthropic_beta, last_finish, pending_tools, opencode_exit}` |
| `post_compaction` | object\|null | For `post_compaction_signature`: the breaking main turn `{call_index, status, prior_side_call_index, prior_side_kind, calls}` |
| `stripped_side_thinking_blocks` | int | Sum, over this trial's main turns, of thinking or redacted_thinking blocks the proxy removed because a side response in the trial had returned that signature or redacted data. `0` when none |
| `smoke_compaction` | object | `{enabled, knob, context_limit, output_limit, usable_tokens, env}`. `enabled` false is the normal window (context 200000, usable 168000). `enabled` true is the opt-in smoke profile (context 72000, usable 40000). Rows with `enabled` true are not comparable with rows that left it false |
| `thinking_block_binding` | string\|null | `drop_block` if any side request was sent with the binding control, `off` if an Anthropic side request was seen and the control was not applied, null when there was no Anthropic side request |
| `workers` | int | The run's fixed worker count |
| `wall_seconds`, `host_load` | number, object | Trial wall time, and `{start, end, cpus}`: the host's 1/5/15-minute load average when the trial started and ended, so contention-driven timeouts are visible |
| `timed_out`, `timeout_detail` | bool, object\|null | The agent hit its cap (`task.toml` `agent_timeout_s`, else 1800 s, the same for both models). Researcher ruling 2026-11-17: if a model call finished in the last 5 minutes before the cap, the agent was still working and the trial is a task **fail** (`status: completed`, `passed: false`, in the denominator; checker exit recorded). Otherwise it is `status: timeout` (infrastructure). `timeout_detail`: `{cap_seconds, last_call_ended_before_cap_s, still_working}`. `wall_seconds`, `host_load` and cost are recorded either way. |
| `trace_warning` | string\|null | The trace could not be built (e.g. `step_call_mismatch: 11 main OpenCode steps but 10 main wire calls`). The checker's verdict stands; `trace` is null. A synthetic continue text after compaction is not this: the trace is written. |
| `trace_warnings` | array\|null | Non-fatal parse warnings. `implicit_text_before_step_start` once per text event recovered in the gap after a compaction (the synthetic continue prompt, or any other text before the next `step_start`). The trace is still written and `steps` is set. Empty when the trace was built and nothing was recovered. Null when the trace was not built. |
| `cost_unpriced_calls` | int | Calls with no cost (e.g. cut off by a timeout before usage arrived). `cost_usd` sums the priced calls, so it is a lower bound when this is > 0. |
| `error` | string\|null | |
| `retry_of` | string\|null | Original trial id when this row re-runs an infrastructure error. Null on the original row, which is kept |
| `attempt` | int | 0 for the original slot; 1, 2, or 3 for a re-run. A slot still infra after attempt 3 is not re-run again |
| `last_vertex_request` | object\|null | Every trial, not only re-runs: the last Vertex call `{sent_at, model, response_arrived, first_byte_at, call_index, status}`. `sent_at` is when the request was sent; `response_arrived` is whether an HTTP response came back; `first_byte_at` is the first body byte. Written to `last_vertex_request.json` when the request is sent, so a hang before any wire line is visible. Null when the trial made no model call |

## Summary row (`openbench.reflection.summary/v1`)

| Field | Meaning |
|---|---|
| `task`, `model`, `patch_id` | The group. `gpt-oss-120b-medium` ("gpt-oss at medium", opt-in) is its own model key, so it is never pooled with `gpt-oss-120b` (effort high). |
| `planned`, `trials`, `completed`, `passes`, `fails`, `errors` | Counts |
| `route_truncated`, `upstream_4xx` | How many of `errors` were `route_truncated` / `upstream_4xx` trials |
| `provider_blocked` | Blocked trials (**not** in `errors`); per-task detail in `provider_blocked.json` (raw blockReason / blockReasonMessage) |
| `model_refused`, `model_refused_checker_passes` | Refused trials (**not** in `errors`), and how many the checker would still pass |
| `set_aside`, `pass_rate_all_fail`, `verdict_all_fail` | Researcher ruling 2026-11-17: blocked and refused trials are neither pass nor fail. They are left out of the denominator: `pass_rate`/`verdict` are over completed trials once every trial is completed or set aside, and a cell with only set-aside trials is `excluded`. The swap rule uses those completed trials. The sensitivity check counts every set-aside trial as a fail (`pass_rate_all_fail`, `verdict_all_fail`; `verdicts.json` `pass_all_fail`). `set_aside.json` has the per-task, per-model table with the refusals and their steps. A cell enters credit assignment and ideation when its set-aside count is at most 3 (about 10% of 30); that count is reported beside the credit rows. |
| `agent_exit_pending_tool`, `checker_error` | How many of `errors` were these infrastructure statuses |
| `side_thinking_signature` | How many of `errors` were a final side-request thinking-signature 400 (`env_cause=vertex_thinking_signature`). Not in the pass/fail formula |
| `post_compaction_signature` | How many of `errors` were a main-turn thinking-signature 400 after a side call (`env_cause=vertex_thinking_signature`). Not in the pass/fail formula |
| `signature_400s` | Sum of the trials' `signature_400s` |
| `stripped_side_thinking_blocks` | Sum of the trials' `stripped_side_thinking_blocks` |
| `workers` | The worker count(s) the group's trials ran under |
| `retried_4xx` | Sum of the trials' `retried_4xx` by status code |
| `image_ids`, `image_matches_pin` | Every image id the group ran; `false` if any trial ran an image that doesn't match its pin, `true` if all matched, `null` if no pin. `verdicts.json` lists such tasks per model as `image_matches_pin_false`. |
| `suite_label`, `code_commits` | The run label, and every commit the group's trials ran from |
| `code_commit` | That checkout when every trial in the group recorded the same one. Null when the group mixed commits or recorded none. Credit-assignment arms (fresh baseline, selection, confirmation, confirmation-baseline) record it, and `evaluate` refuses an arm whose `code_commit` differs from the fresh baseline's `baseline_commit` |
| `model_calls`, `tool_call_turns`, `route_repairs` | Sums of the trials' `route_counts`. Always 0 repairs for Carbon and Opus, which are never rewritten. |
| `unknown_recipient_calls` | **Model errors:** gpt-oss tool calls to a tool we never offered (e.g. `repo_browser.print_tree`). They are never remapped onto our tools; OpenCode answers them with its `invalid` tool's error. Included in `route_repairs`. Every rebuilt call is also logged per cell by the executor (`<model>/<task>/route_repairs.jsonl`). |
| `route_repair_share` | `route_repairs / tool_call_turns`: the share of gpt-oss's tool calls that exist only because of our parser (`null` with no tool calls) |
| `trials_with_route_repair`, `passes_with_route_repair` | Trials with at least one repair, and how many of those passed: the passes that depend on the parser |
| `trials_without_route_counts` | Trials with no wire counts (crashes), left out of the sums |
| `pass_rate` | `passes / completed` |
| `cutoff`, `verdict` | `pass` iff the settled outcomes (completed trials, plus refused and blocked trials set aside) cover `planned` and `passes / completed >= cutoff` (exact; 27/30 at 0.90). `incomplete` when a slot has no settled outcome. The swap rule is unchanged: it sees `(passes, completed)` for a pass or fail verdict only. An infrastructure row kept beside a successful re-run still counts in `errors`; it is not a settled outcome, so it does not by itself keep the verdict incomplete once every slot has settled. |
| `incomplete_reason` | Set when the verdict is `incomplete` because a slot is still an infrastructure error after 3 re-runs (`infra retry cap: trial_index N still <status> after 3 re-runs`). Null when the cell is incomplete only because trials have not finished, and null when the verdict is pass, fail, or excluded |
| `infra_retry_exhausted` | Those slots: `{trial_index, trial_id, retries, last_status}`. Empty when none. A later resume does not re-run them |
| `spend_usd`, `spend_complete` | Sum of trial costs. `spend_complete` is false if any trial had no cost or unpriced calls. |
| `trace_warnings` | Trials whose trace could not be built (`trace_warning` set) but whose checker verdict stands. The trial field of the same name is the non-fatal list and does not by itself increment this count. |
| `timed_out`, `timeout_fails` | Trials that hit the cap, and how many of them were task fails (agent still working) |
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
- `ideation_estimate(executor, {model: failures}, confirm="all", cells=None, confirm_k=1)` prices ideation.
  `confirm` is `all` (default) or `top`, the same setting as
  `evaluate(..., confirm=)`. `cells` is `{model: cell count}`, required for `top`.
  `confirm_k` defaults to 1 and must be an int >= 1 (a value other than 1
  requires `confirm=top`):
  - selection: `failures × 5 × N` trials;
  - `confirm=all`: confirmation is `failures × 5 × candidate_fraction × 2N`
    trials (a fresh alternative run plus a fresh baseline run for every
    candidate);
  - `confirm=top`: confirmation is `cells × confirm_k × 2N` trials, because
    the cell confirms that many candidates across its drawn failures, each
    with its own fresh baseline;
  - the worst case for `all` (every alternative a candidate) is 3× selection.
    For `top` it is `confirm_k` confirmations per cell (`confirm_k × 2N` trials)
    on top of selection.
- During the run, spend is the sum of logged trial costs. Every trial, including an infrastructure re-run, checks the cap and the alert thresholds before it starts. Trials already running count as their per-trial estimate, so concurrent workers cannot together pass the cap.
- Credit-assignment invocations (`credit_baseline`, `evaluate`, the ideation CLI) use that same check through `SpendLedger`. `max_usd_per_cell` is `spend_cap_usd` for one `(model, task)` cell. `max_usd` is the experiment total. At startup the ledger reads every `trials.jsonl` under `credit_baseline/` and `ideation/`, so a restart keeps both caps cumulative. A trial id is stored once. A running trial with no row yet is reserved at its estimate; a landed row counts at its recorded cost only. See `CREDIT_ASSIGNMENT.md`.

## Credit-assignment agreement

`credit_agreement.jsonl` is one row per drawn failure (`credit_draw.json`, status `IN`). An admitted failure that was not drawn is absent, and the summary counts are over the drawn rows only. Method B's judge runs on those same drawn failures.

`same_step` is kept and is tautological: Method B's first failing step is the shared locator step Method A records, because B's window is built from that step. `earliest_near_error_step` is the earliest step in B's window that the judge labels `near_error` (null when none of the window is `near_error`, or when the window is empty). `steps_before_a` is Method A's step minus that step (null when either is unavailable).

## Infrastructure re-runs

Settled outcomes are `completed` (passed or failed, including a timeout where a model call finished in the last 300 seconds and the agent was still working), `model_refused`, and `provider_blocked`. `INFRA_STATUSES` in `runner.py` is everything else (`error`, `timeout`, `route_truncated`, `upstream_4xx`, `agent_exit_pending_tool`, `side_thinking_signature`, `post_compaction_signature`, `checker_error`). An infra timeout is re-run; a still-working timeout is a task fail and is not. `side_thinking_signature` and `post_compaction_signature` are infrastructure the same way; they do not change how a pass or fail is computed.

## Smoke compaction

OpenCode at pin `ba54cee55e18b47fb70badc84ae2cbac7c83d258` decides to compact in `packages/opencode/src/session/compaction.ts` `isOverflow`. With no `limit.input` on the model, the usable window is `limit.context` minus `maxOutputTokens` (`packages/opencode/src/provider/transform.ts`: `min(limit.output, 32000)`). The reflection config sets context 200000 and output 32000, so the window is 168000 tokens and a short smoke rarely crosses it.

`provider/provider.ts` copies `limit.context` and `limit.output` from the config model and does not copy `limit.input`, so `compaction.reserved` (which only applies when `limit.input` is set) cannot lower the threshold for this provider. `OPENCODE_DISABLE_AUTOCOMPACT` only turns auto compaction off. There is no env var that forces a compaction by itself.

The opt-in knob is OpenCode's own `limit.context`, written into `OPENCODE_CONFIG_CONTENT` by the harness. `--smoke-compaction` or `OBENCH_SMOKE_COMPACTION=1` (or `smoke_compaction: true` in the run config) sets it to 72000. For the Opus model the reflection config sets `limit.output` to 32000 and does not set `limit.input`, so `maxOutputTokens` is `min(32000, 32000) = 32000` and the usable window is `72000 - 32000 = 40000`. `session/processor.ts` returns `"compact"` when a step's token count reaches that window (including when that step's finish reason is `stop`), and the next loop iteration runs the compaction side request. Default off. The pinned OpenCode binary is not patched. `plan.json` `smoke_compaction` and each trial row's `smoke_compaction` record `enabled`, the context limit, and the usable window.

```bash
python3 -m obench.reflection.runner --resume <run_dir> --retry-infra --dry-run
python3 -m obench.reflection.runner --resume <run_dir> --retry-infra --cell --opencode <bin> --use-image-tag
```

`--dry-run` prints, per cell, `settled`, `infra`, and `would_rerun`, and runs nothing. Re-runs are scheduled in the same order as ordinary trials (trial index, then suite slot, then model), one new attempt per wave, at most 3 per slot. Each new row has `retry_of` set to the original trial id. The original row stays in `trials.jsonl`.

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
