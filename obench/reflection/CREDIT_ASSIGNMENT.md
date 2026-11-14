# Credit assignment (SEA-108 Method A, SEA-109 Method B)

Both methods read the **same** failed trials of a runner run: rows in
`trials.jsonl` with `status: completed` and `passed: false`, plus each
trial's `trace.jsonl` (`openbench.reflection.step/v1`). Each method writes
**its own table** in the run directory: `credit_a.jsonl` for A and
`credit_b.jsonl` for B. Neither writes into `trials.jsonl` or into the other's
table. They are two views of one dataset, not two datasets.

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
Any change to the rule bumps `LOCATOR_RULE_VERSION`.

## Method A (`credit_a.py`, rule `A1+locator-v1`)

Method A is the locator's answer, with a rationale. One row per failed trial,
schema `openbench.reflection.credit_a/v1`:

| Field | Meaning |
|---|---|
| `rule_version` | `A1+locator-v1` |
| `run_id`, `trial_id`, `task`, `model`, `patch_id` | The failed trial |
| `failing_step` | 1-based trace step (null for an empty trace) |
| `signal`, `tool`, `evidence` | What triggered it: the signal, the tool name, and a short excerpt |
| `rationale` | One sentence, generated from the signal |
| `steps_total` | Steps in the trace |
| `trace`, `trace_step` | Pointer to the trace and `trace#step=N` (relative) |

Run it with `python3 -m obench.reflection.credit_a --run <run dir>`. The
table is rewritten whole, so a rerun is idempotent.

## Method B (`credit_b.py`, prompt `B1`)

1. Find the first failing step `f` with the shared locator.
2. Ask a **System 1 model** to label each of the `K` steps before `f` as
   `correct` or `near_error` (contributed to the failure). The prompt is
   deterministic for the same inputs. The request uses temperature 0, a JSON
   response schema, and an explicit thinking setting.
3. Assign weights to every step:
   - steps before the window: `correct_weight` (1);
   - window steps labelled `correct`: `correct_weight` (1);
   - window steps labelled `near_error`: `near_error_weight`;
   - `f` and every later step: `past_cutoff_weight` (0). The cutoff rule is
     `first_failing_step_onward`.

### Config (`MethodBConfig`, or `--config` JSON). Open items: provisional, not final

| Key | Default | Status |
|---|---|---|
| `k` | **2** | **Provisional** (open) |
| `near_error_weight` | **0.5** | **Provisional** (open) |
| `correct_weight` / `past_cutoff_weight` | 1.0 / 0.0 | The scheme in the ticket |
| `cutoff_rule` | `first_failing_step_onward` | |
| `system1_model` | **`gemini-3.8-flash`** (Gemini Flash, Vertex `global`; the newest GA Flash, released 2026-09-02) | **Open:** Sean called the model "Jev". Until he confirms whether "Jev" is a specific endpoint, Gemini Flash is the default. Switching is a one-line config change. |
| `system1_thinking` | `{"thinkingLevel": "LOW"}` | Set explicitly on every judge request (standing rule). Provisional level. |

### Table (`credit_b.jsonl`, schema `openbench.reflection.credit_b/v1`)

| Field | Meaning |
|---|---|
| `prompt_version`, `locator_rule_version` | `B1`, `locator-v1` |
| `run_id`, `trial_id`, `task`, `model`, `patch_id` | The failed trial (the same rows as Method A) |
| `system1_model`, `system1_thinking` | The judge and its thinking setting |
| `k`, `near_error_weight`, `correct_weight`, `past_cutoff_weight`, `cutoff_rule` | The config this row used |
| `first_failing_step`, `signal` | From the shared locator |
| `window` | The steps the judge labelled (`f-K .. f-1`, those that exist) |
| `labels` | `{step: correct\|near_error}` |
| `weights` | `[{step, weight, why}]` for every trace step (`why`: `before_window`, `correct`, `near_error`, `past_cutoff`) |
| `raw_judge_output`, `judge_usage` | The judge's raw text and its usage, for audit |
| `judge_error` | Set when the judge failed or answered in an unparseable form (then `weights` is null), or `empty_trace` |
| `trace` | Pointer to the trial's trace |

Run it with `python3 -m obench.reflection.credit_b --run <run dir> [--config b.json]`.
It needs `GOOGLE_CLOUD_PROJECT` and Google credentials (ADC). It's paid, but tiny:
one Flash call per failed trial.
