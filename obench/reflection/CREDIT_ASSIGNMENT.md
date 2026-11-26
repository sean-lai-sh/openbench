# Credit assignment (SEA-108 Method A, SEA-109 Method B)

Both methods read the **same** failed trials of a runner run: rows in
`trials.jsonl` with `status: completed` and `passed: false`, plus each
trial's `trace.jsonl` (`openbench.reflection.step/v1`). Each method writes
**its own table** in the run directory: `credit_a.jsonl` for A and
`credit_b.jsonl` for B. Neither writes into `trials.jsonl` or into the other's
table. They are two views of one dataset, not two datasets.

## Which cells enter

A cell is one `(task, model, patch_id)`. Set-aside trials are `provider_blocked`
and `model_refused` (Researcher ruling 2026-11-17: neither pass nor fail, and
left out of the pass-rate denominator). The amended rule: the cell enters
credit assignment when `set_aside_count <= max_set_aside`. The default
`max_set_aside` is **3**, about 10% of an N=30 cell. A cell with 0, 1, 2, or 3
set-aside trials enters, and its completed failures are scored. A cell with 4
or more stays out.

`max_set_aside` is exposed the same way the other driver settings are:

- Method A: `python3 -m obench.reflection.credit_a --run <run dir> [--max-set-aside 3]`
- Method B: `max_set_aside` on `MethodBConfig` (the `--config` JSON). `--max-set-aside` overrides that file.

Every credit row records `max_set_aside` and that cell's `set_aside_count`
beside the trial's result. Ideation uses the same cap
(`evaluate(..., max_set_aside=3)`, read from the fresh baseline's `set_aside`).

## Rule 2: `cap_cutoff` (Researcher, 2026-11-25)

A failed trial that hit the agent cap is `cap_cutoff` when its trace contains
no tool error anywhere. It is dropped from the locator, from credit assignment,
and from the seeded draw below. The filter lives in the draw driver
(`credit_draw.py`). The locator is unchanged: `first_failure()` still returns
`final_answer_rejected` at the last step for a trace with no tool error, and
`LOCATOR_RULE_VERSION` stays `locator-v1`.

- **Hit the cap.** The trial is a completed failure (`status: completed`,
  `passed: false`) with `timed_out` set: the agent was still working when the
  task cap fired. An infrastructure timeout (`status: timeout`) is not a
  failure and is not `cap_cutoff`.
- **No tool error anywhere.** No step has `step_error`: a tool call with
  `status: error`, or a result matching `ERROR_PATTERNS`. The driver searches
  the whole trace. It does not ask the locator for a new signal.
- **A timeout with a tool error stays in.** It is eligible, and the locator
  would place it at that error step.
- **A timeout with no trace is not `cap_cutoff`.** There is nothing to search.
  A missing path, a missing file, or a trace with no steps is no-trace. Those
  trials are recorded and are not eligible. They are not rebuilt here.

`credit_a` and `credit_b` still score every admitted failure they are given.
The driver is what leaves `cap_cutoff` trials out of the set those stages
will be handed. Running Method A or B on a run directory directly does not
apply rule 2.

## Seeded failure draw (`credit_draw.py`)

The candidate cells are an explicit list, passed as `--cells`. The driver does
not infer candidates from `trials.jsonl`. A cell that appears in the rows and
is absent from the list is recorded as `NOT_LISTED` with `reason` `not in the
cell list`, an empty `picks` list, and `eligible_pool` 0. Nothing is drawn for
it. A listed cell that has no rows in `trials.jsonl` is `NO_ROWS` with `reason`
`no rows in trials.jsonl`, an empty `picks` list, and `eligible_pool` 0.
Nothing is drawn for it. That is not `IN` with an empty pool: a listed cell
that has rows, and no eligible failure left after the filters, stays `IN`.
A typo in the cell list is `NO_ROWS`. A listed cell over the set-aside cap
stays `EXCLUDED`. The cap rule is unchanged.

`--cells` is a text file, one `<model>/<task>` key per line (blank lines and
`#` comments ignored), or a JSON array of those keys, or `{"cells": [...]}`.
A key may add `@<patch_id>` when that patch is itself a candidate. The SEA-111
v2 plan list is `obench/tests/fixtures/sea111_v2_cells.txt`: the 8 cells that
enter and `gemini-4-carbon/dna-insert`.

For each listed cell the pool is built in this order:

1. Start from `failed_trials()` (completed failures whose cell has
   `set_aside_count <= max_set_aside`).
2. Remove `cap_cutoff` trials.
3. Remove trials with no trace.
4. Sort the remaining trial ids and draw.

```text
cell   = "<model>/<task>"                 # "@<patch_id>" when patch_id is set
digest = sha256(("sea111-" + cell).encode("utf-8")).hexdigest()
picks  = random.Random(int(digest, 16)).sample(sorted(eligible_trial_ids), n_pick)
```

`cell` is the same `<model>/<task>` key as the pilot cells, for example
`claude-opus-5-5/model-extraction-relu-logits`. A cell is still
`(task, model, patch_id)` for admission, matching `failed_trials()`. When
`patch_id` is set, the seed key gains `@<patch_id>` so two patches do not
share a draw. Picks stay in the order `sample` returned. `draw_order` starts
at 1. The same cell and the same pool always produce the same picks
(Python 3 `random.Random`, the digest as an int seed).

`n_pick` defaults to **3**. `--n-pick all` (or `"n_pick": "all"` in the config)
draws every eligible failure, a seeded sample of the whole pool. When a cell
has fewer eligible failures than `n_pick`, the draw is the whole pool.

A listed cell with `set_aside_count > max_set_aside` is `EXCLUDED`. Nothing is
drawn (`eligible_pool` 0, `picks` empty). The manifest still lists that cell's
`cap_cutoff` trials and no-trace failures. The reason is the count, for
example `max_set_aside=3: 5 set-aside (provider_blocked) trials > 3`. No task
name is special-cased. The set-aside cap applies only to listed cells. A cell
in the rows that the list does not name is `NOT_LISTED`, with nothing drawn.
A listed cell with no rows is `NO_ROWS`, with nothing drawn.

The driver writes `credit_draw.json` in the run directory (one object keyed by
cell) and one file per cell under `credit_draw/`. A rerun replaces them.
`trials.jsonl` is not modified. Neither file stores trace paths.

| Field | Meaning |
|---|---|
| `cell`, `seed_string`, `seed_sha256` | `<model>/<task>` (plus `@patch` when set), `sea111-` + that key, and its sha256 |
| `status`, `reason` | `IN` (`reason` null), `EXCLUDED` with the set-aside reason, `NOT_LISTED` with `not in the cell list`, or `NO_ROWS` with `no rows in trials.jsonl` |
| `eligible_pool` | How many trials remained after the cap filter and the no-trace filter. 0 when the cell is excluded, not listed, or has no rows |
| `n_pick` | How many the draw was asked for (`3` or `all`) |
| `picks` | `{draw_order, slot, trial_id}` in draw order. `slot` is the trial's `trial_index` |
| `cap_cutoff_dropped` | `{slot, trial_id}` for rule 2, including on an excluded cell |
| `no_trace_count`, `no_trace_trials` | Completed failures with no usable trace (`{slot, trial_id}`) |
| `set_aside_count`, `max_set_aside` | The cell's set-aside count and the cap that admitted or excluded it |

```text
python3 -m obench.reflection.credit_draw --run <run dir> --cells <cell list> [--n-pick 3|all] [--max-set-aside 3] [--config draw.json]
```

`--config` is a `DrawConfig` JSON object (`n_pick`, `max_set_aside`).
`--n-pick` and `--max-set-aside` override the file when passed. The default
cap is 3, the same setting as Method A and Method B.

## Fresh baseline (`credit_baseline.py`)

Before selection, each admitted cell (a listed cell the draw would mark `IN`)
gets a fresh N-trial baseline at the current checkout. N defaults to **30**.
`EXCLUDED` and `NO_ROWS` cells are not run. The trials are a new run under
`credit_baseline/runs/`. `trials.jsonl` is not modified.

The image is the one recorded on that cell's original trials (`image_ref`,
`image_id`, `image_matches_pin`). It is reused as `recorded_image`. The step
does not re-pin: a missing image, two different recorded images, or a fresh
trial that ran a different ref is an error. The smoke-compaction knob is off
for this run, including when `OBENCH_SMOKE_COMPACTION` is set. A rerun is
checked in a side directory and replaces the published baseline only after
that check passes. A failed rerun leaves the previous manifest and its trials
in place.

`credit_baseline.json` (and one file per cell under `credit_baseline/`) records:

| Field | Meaning |
|---|---|
| `baseline_commit` | The checkout the fresh trials ran |
| `code_commit` | The same checkout, recorded on this arm. `evaluate` refuses any arm (this baseline, selection, confirmation, confirmation-baseline) whose `code_commit` differs from `baseline_commit` |
| `image` | `{ref, id}` from the cell's original trials |
| `image_matches_pin` | The recorded flag, kept when it is false |
| `image_matches_pin_false` | True when `image_matches_pin` is false, so the mismatch is visible on the row |
| `passes`, `completed` | The fresh run |
| `set_aside` | Set-aside trials in the fresh run |
| `cost_usd` | Spend of the fresh run |
| `smoke_compaction` | False |

`evaluate` scores selection against this row. A cell with no fresh baseline is
an error. The pilot `summary.jsonl` row is not a fallback (`summary_row_baseline`
raises if called).

Selection (SEA-110): an alternative is a candidate when its passes are greater
than this fresh baseline's passes and both sides completed N. A tie is not a
candidate. Confirmation runs a new N-trial alternative and a new N-trial
baseline, and the candidate is confirmed only when the alternative has more
passes than that new baseline. `confirm=all` (the default) confirms every
candidate. `confirm=top` confirms the top `confirm_k` candidates per cell
`(model, task)` (default `confirm_k` 1). The pool is that cell's drawn
failures, ranked by most selection passes, then the earlier seeded pick
(`draw_order` in `credit_draw.json`), then the lower alternative index, then
`proposal_id`. Fisher p is not part of that ranking. A cell with fewer than
`confirm_k` candidates confirms every candidate. Every other candidate stays
a candidate with `confirm_skipped: not_top`. Each confirmed candidate keeps
its own fresh N-trial alternative run and its own fresh N-trial baseline.
`confirm_k` is an integer >= 1. A value other than 1 is an error when
`confirm` is `all`. `confirm` and `confirm_k` are recorded on every result
row. A cell whose drawn failures are not all selected yet stays unconfirmed
(`confirmed` null and `confirm_skipped` null).
The one-sided Fisher exact p is written on the result and is not a gate. `evaluate` does not take an `alpha` argument and
always uses `ALPHA` (1.0). The result row records that `alpha` and the fresh
baseline's `baseline_commit`. `evaluate` refuses to write a row whose alpha is
not 1.0. `decide(alpha=...)` stays available for a library check. Any p-gated
view of a result belongs only in a report, as a separate sensitivity column
computed from the recorded Fisher p. That column never changes `candidate`,
`confirmed`, or `success`.

Every arm (fresh baseline, selection, confirmation, and the confirmation
baseline) records `code_commit` and is run on the fresh baseline's recorded
image, with smoke compaction off. A trial that reports a different ref or id
is refused. The image is not re-pinned. `evaluate` refuses an arm whose
`code_commit` differs from this row's `baseline_commit`.

```text
python3 -m obench.reflection.credit_baseline --run <run dir> --cells <cell list> --fixture <passes.json> [--n-trials 30]
python3 -m obench.reflection.credit_baseline --run <run dir> --cells <cell list> --live --opencode <bin/<sha>/opencode> [--n-trials 30]
```

Exactly one of `--fixture` and `--live` is required. `--fixture` is the offline
pass table and does not start a provider. `--live` builds a `CellExecutor`,
the same executor `python3 -m obench.reflection.runner --cell` builds (one
container of the recorded image per trial, pinned OpenCode, recording proxy),
and passes it to `run_baselines`. `--live` needs `GOOGLE_CLOUD_PROJECT` and
`--opencode`. `--estimates`, `--default-image`, and `--use-image-tag` match
`runner --cell`. Smoke compaction stays off. This baseline runs on the same
VM as the selection and confirmation arms.

## Shared first-failure locator (`credit_locator.py`, `locator-v1`)

1. Walk the steps in order. A step **fails** when one of its tool calls has an
   error signal:
   - `tool_error_status`: the call's `status` is `error`. This includes errored
     calls that SEA-104 recovered from the next request.
   - `tool_error_output`: the call's result matches `ERROR_PATTERNS`: a Python
     traceback, a line-leading `error:` or `fatal:` (compilers, git, cargo),
     `command not found`, `No such file or directory`, a non-zero
     exit/exit code, a line-leading `FAILED` (test runners), or `Segmentation fault`.
2. The **first** failing step is the result, **even if the agent recovers
   later**. It marks where the trajectory first went wrong.
3. No error signal anywhere means `final_answer_rejected`: the last step, which
   ended the run with a result the checker rejected.
4. An empty trace means `empty_trace`, and `failing_step` is null.

Both methods call `first_failure()`, so A and B can't disagree on the step.
Any change to the rule bumps `LOCATOR_RULE_VERSION`. Rule 2 is not such a
change: `cap_cutoff` trials are filtered out by the draw driver before a
trial is handed to the locator.

## Method A (`credit_a.py`, rule `A1+locator-v1`)

Method A is the locator's answer, with a rationale. One row per failed trial,
schema `openbench.reflection.credit_a/v1`:

| Field | Meaning |
|---|---|
| `rule_version` | `A1+locator-v1` |
| `run_id`, `trial_id`, `task`, `model`, `patch_id` | The failed trial |
| `set_aside_count` | Set-aside trials in this cell (provider-blocked plus model-refused), reported beside the result |
| `max_set_aside` | The cap that admitted the cell (default 3). The cell entered because `set_aside_count` <= this |
| `failing_step` | 1-based trace step (null for an empty trace) |
| `signal`, `tool`, `evidence` | What triggered it: the signal, the tool name, and a short excerpt |
| `rationale` | One sentence, generated from the signal |
| `steps_total` | Steps in the trace |
| `trace`, `trace_step` | Pointer to the trace and `trace#step=N` (relative) |

Run it with `python3 -m obench.reflection.credit_a --run <run dir> [--max-set-aside 3]`. The
table is rewritten whole, so a rerun is idempotent.

## Method B (`credit_b.py`, prompt `B1`)

`run_method_b` judges **drawn failures only**. It reads `credit_draw.json` and
labels the picks of `IN` cells. An admitted failure that was not drawn gets
no row and no judge call. A missing `credit_draw.json` is an error. Method A
is unchanged and still scores every admitted failure. `method_b_row` does
not read the draw.

1. Find the first failing step `f` with the shared locator.
2. Ask a **System 1 model** to label each of the `K` steps before `f` as
   `correct` or `near_error` (contributed to the failure). The prompt is
   deterministic for the same inputs. The request uses temperature 0, a JSON
   response schema, and an explicit thinking setting. A window shorter than
   `K` (the failure is early, so some of `f-K .. f-1` do not exist) is
   labelled as it is. The row records `window_length`, how many steps were
   actually in the window. It is not padded and not dropped.
3. When `f` is step 1 there is no prior step. The row's `status` is
   `empty_window`, `window` is empty, `window_length` is 0, and the judge is
   not called. Weights still follow the cutoff rule. The ideator for that
   failure receives only Method A's evidence, and the proposal row records
   `method_b_status: empty_window` and `ideator_evidence: ["A"]`.
4. Assign weights to every step:
   - steps before the window: `correct_weight` (1);
   - window steps labelled `correct`: `correct_weight` (1);
   - window steps labelled `near_error`: `near_error_weight`;
   - `f` and every later step: `past_cutoff_weight` (0). The cutoff rule is
     `first_failing_step_onward`.

### Config (`MethodBConfig`, or `--config` JSON). Open items: provisional, not final

| Key | Default | Status |
|---|---|---|
| `k` | **4** | Sean, 2026-11-13 (was a provisional 2) |
| `near_error_weight` | **0.5** | Kept for now (Sean, 2026-11-13) |
| `correct_weight` / `past_cutoff_weight` | 1.0 / 0.0 | The scheme in the ticket |
| `cutoff_rule` | `first_failing_step_onward` | |
| `system1_model` | **`gemini-3.8-flash`** (Gemini Flash, Vertex `global`; the newest GA Flash, released 2026-09-02) | **Open:** Sean called the model "Jev". Until he confirms whether "Jev" is a specific endpoint, Gemini Flash is the default. Switching is a one-line config change. |
| `system1_thinking` | `{"thinkingLevel": "LOW"}` | Set explicitly on every judge request (standing rule). Provisional level. |
| `max_set_aside` | **3** | A cell enters when its set-aside count is at most this (about 10% of 30). `--max-set-aside` overrides the config file. |

### Table (`credit_b.jsonl`, schema `openbench.reflection.credit_b/v1`)

| Field | Meaning |
|---|---|
| `prompt_version`, `locator_rule_version` | `B1`, `locator-v1` |
| `run_id`, `trial_id`, `task`, `model`, `patch_id` | The failed trial (the same rows as Method A) |
| `set_aside_count`, `max_set_aside` | The cell's set-aside count, reported beside the result, and the cap that admitted it |
| `system1_model`, `system1_thinking` | The judge and its thinking setting |
| `k`, `near_error_weight`, `correct_weight`, `past_cutoff_weight`, `cutoff_rule` | The config this row used |
| `first_failing_step`, `signal` | From the shared locator |
| `window` | The steps the judge labelled (`f-K .. f-1`, those that exist) |
| `window_length` | How many of those steps exist. A short window is less than `k` and is still labelled |
| `status` | `ok` when the window was labelled (including a short window), `empty_window` when the failure is at step 1, `empty_trace` when the trace has no steps, `judge_error` when the judge failed |
| `labels` | `{step: correct\|near_error}` |
| `weights` | `[{step, weight, why}]` for every trace step (`why`: `before_window`, `correct`, `near_error`, `past_cutoff`) |
| `raw_judge_output`, `judge_usage` | The judge's raw text and its usage, for audit |
| `judge_error` | Set when the judge failed or answered in an unparseable form (then `weights` is null), or `empty_trace` |
| `trace` | Pointer to the trial's trace |

Run it with `python3 -m obench.reflection.credit_b --run <run dir> [--config b.json] [--max-set-aside 3]`.
It needs `GOOGLE_CLOUD_PROJECT` and Google credentials (ADC), and `credit_draw.json`
in the run directory. It's paid, but tiny: one Flash call per drawn failure
that has a window. An undrawn trial, an `empty_window` row, or an
`empty_trace` row makes no call.

## A/B agreement (`credit_agreement.jsonl`)

The pilot compares Method A and Method B on this table only. Ideation sees
both methods in one input, so an alternative's later result is not attributed
to one method. The table is the pre-registered draw: one row per pick of an
`IN` cell in `credit_draw.json`, and only those. Method A still covers every
admitted failure; an admitted failure that was not drawn is absent here, even
when both credit tables have a row for it. Summary counts (`rows`,
`probe_errors`, `same_step`) are over the drawn rows only. A missing
`credit_draw.json` is an error. A drawn trial missing a Method A or Method B
row is an error. Method A's locator is unchanged: the first failure stays the
first failure, including an exploratory probe the agent recovered from.

```text
python3 -m obench.reflection.credit_agreement --run <run dir>
```

That command reads the draw and the two credit tables. It does not call a model.

| Field | Meaning |
|---|---|
| `trial_id`, `task`, `model`, `patch_id` | The drawn failure |
| `drawn` | True. Every stored row is a drawn pick, so this column is true on each of them |
| `method_a_step`, `method_a_signal` | Method A's failing step and signal |
| `method_b_step`, `method_b_status`, `method_b_window`, `method_b_window_length` | Method B's step, status, window, and actual window length |
| `same_step` | Method A's step equals Method B's step (both non-null). Tautological: both steps are the shared locator's first failure, and B's window is built from that step. The column stays so the pre-registered table does not drop it |
| `earliest_near_error_step` | The earliest step in B's window that B's judge labels `near_error` (contributing). Null when none of the window is `near_error`, or when the status is `empty_window` (also null for an empty trace or a judge error) |
| `steps_before_a` | Method A's step minus `earliest_near_error_step`. Null when that step is null or Method A's step is null |
| `near_error_steps`, `near_error_count` | Window steps Method B labelled `near_error`, and how many |
| `probe_error` | True when Method A's first failure is a tool error (`tool_error_status` or `tool_error_output`) at step 3 or earlier |
| `probe_error_step` | That step, or null when `probe_error` is false |

`final_answer_rejected` is not a probe error, including on a trace that ends at step 3. A tool error at step 4 or later is not a probe error. A tool error at step 1 is both `probe_error` and Method B `empty_window`.
