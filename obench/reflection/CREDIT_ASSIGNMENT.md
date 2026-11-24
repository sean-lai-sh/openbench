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
