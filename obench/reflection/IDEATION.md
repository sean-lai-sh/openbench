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

## Evaluation and the success rule (`ideation_results.jsonl`)

Each accepted proposal runs **N = 30** trials (`runner.N_TRIALS`) on the
parent's task and model. It goes through the SEA-107 runner, into
`ideation/<proposal_id>/`, with `patch_id` set (patch runs never swap the
suite).

`decide(baseline, alternative)`:
1. **Both sides must have completed all N trials.** Otherwise the result is
   `complete: false` and is not judged.
2. `beats_baseline`: alternative passes > baseline passes (the ticket's
   minimum bar).
3. **`success`**: `beats_baseline` **and** a one-sided Fisher exact test,
   `p <= ALPHA` (0.05). A single lucky pass never counts: 1/30 vs 0/30 gives
   p = 0.5. 6/30 vs 0/30 gives p ≈ 0.012 and counts.

Result rows record the baseline and alternative passes, completed counts,
spend, `fisher_p`, `beats_baseline`, `success` and `credit_method`. Set
`ALPHA = 1.0` to fall back to the bare "beats the baseline at N=30" rule.
