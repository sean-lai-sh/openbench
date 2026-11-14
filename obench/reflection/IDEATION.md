# Ideation (SEA-110)

`ideation.py` and `patches.py`. Run per failed trial, after credit assignment.

## Allowed change surface: enforced by construction

A proposal is a patch, `{"schema": "openbench.reflection.patch/v1", "ops": [...]}`.
It may contain at most 8 ops from a **closed set**:

| Op | Fields | Changes |
|---|---|---|
| `system_append` | `text` | Appends to the system prompt |
| `system_replace` | `find`, `replace` | Replaces text in the system prompt |
| `tool_description` | `tool`, `description` | A tool's description |
| `tool_param_description` | `tool`, `param`, `description` | One parameter's description |

The recording proxy (`wire_proxy.WireProxy(patch=...)`) applies the patch to
every model request of the alternative's trials. It handles the Anthropic,
OpenAI-chat and Gemini wire formats, and logs per op whether anything changed
(`thinking_enforced.patch_log`, plus `patch_id` on the wire record).

**Out of surface, rejected by `validate_patch`:**
- unknown ops;
- extra keys on a patch or op, such as `file`, `diff` or `temperature`;
- task instructions, checkers or agent code;
- model, route or sampling changes;
- tool type or schema changes other than descriptions;
- message history.

Rejected proposals are stored with reasons and never run.

## Proposals (`ideation.jsonl`, `openbench.reflection.ideation/v1`)

- The ideator (`IDEATOR_MODEL`, default `claude-opus-5-5` on Vertex, thinking
  set explicitly; **open**, configurable) gets the trial's task, model, trace
  and its credit rows from Method `A`, `B` or `A+B`.
- It must return **exactly 5** alternatives. A wrong count or any invalid patch
  gets one re-ask with the reasons.
- Each row records:
  - `prompt_version` (`I1`) and `ideator_model`;
  - `parent_trial_id`, `task`, `model`;
  - **`credit_method`** and `credit_rows` (pointers into `credit_a.jsonl` / `credit_b.jsonl`);
  - `rationale`, `patch` and `proposal_id` (a hash of the patch);
  - `status` (`accepted` or `rejected`), `rejection_reasons` and `complete_set`;
  - the raw ideator output and its usage.

## Evaluation: selection, then confirmation (`ideation_results.jsonl`)

Two stages (João Sedoc via Sean, 2026-11-13). `evaluate(run_dir, proposal, executor)` runs both.

1. **Selection.** The alternative runs **N = 30** trials on the parent's task
   and model, with its patch (`ideation/<proposal_id>/select/`). It is a
   **candidate** iff both it and the original baseline completed all N trials
   and it has **more passes** (`decide`: a bare beat, no significance gate).
   **1/30 vs 0/30 qualifies.**
2. **Confirmation (candidates only).** A **fresh** N-trial run of the
   alternative (`.../confirm/`) **and** a **fresh** N-trial baseline run with
   no patch (`.../confirm-baseline/`). Each arm has its own run id, so its
   trial ids are new, and no selection trial is reused. OpenCode has no
   sampling seed: every trial is an independent sample. **`success`** iff the
   alternative beats the fresh baseline again: full N on both sides, more
   passes.

Every arm runs through the SEA-107 runner in `fixed_tasks` mode: exactly the
parent's task (even a pool task), never a suite swap.

**Columns, one row per evaluated proposal:**

| Stage | Columns |
|---|---|
| Selection | `selection_baseline_passes`, `selection_baseline_completed`, `selection_alt_passes`, `selection_alt_completed`, `selection_beats_baseline`, `selection_complete`, `selection_fisher_p`, `candidate`, `selection_spend_usd`, `selection_run_dir`, `selection_run_state` |
| Confirmation | `confirmation_baseline_passes`, `confirmation_baseline_completed`, `confirmation_alt_passes`, `confirmation_alt_completed`, `confirmation_beats_baseline`, `confirmation_complete`, `confirmation_fisher_p`, `confirmed`, `confirmation_spend_usd`, `confirmation_run_dirs`, `confirmation_run_states`. All null for non-candidates. |
| Outcome | `success` (= `confirmed`), `credit_method`, `parent_trial_id`, `task`, `model`, `n_trials` |

`*_fisher_p` is the one-sided Fisher exact p for that stage, **reported only,
never a gate** (`ALPHA = 1.0`). Passing `alpha=0.05` to `decide` re-enables a
gate for sensitivity analysis.

## Cost

`runner.ideation_estimate(executor, {model: failures}, n_alternatives=5,
n_trials=30, candidate_fraction=1.0)`:
- selection costs `failures × 5 × 30` trials;
- confirmation adds `failures × 5 × candidate_fraction × (30 + 30)` trials
  (the fresh alternative plus the fresh baseline).

The worst case (`candidate_fraction = 1`) is 3× the selection cost. For
example, one failure at Opus's provisional $2/trial costs $300 to select and
up to $600 more to confirm.
