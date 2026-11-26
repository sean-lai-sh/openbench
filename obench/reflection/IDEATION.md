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

`propose_drawn(run_dir, ideator)` is the driver. It asks the ideator **once
per drawn failure** (`credit_draw.json` picks of `IN` cells, in cell order
then `draw_order`). `EXCLUDED`, `NOT_LISTED`, and `NO_ROWS` cells are not
ideated. That one input contains Method A and Method B evidence together
(prompt `I2`). It is not one ideation per method. A re-ask is still that
same failure.

A single-method `propose(..., "A"|"B")` remains for a library check (prompt
`I1`) and does not require citations.

- The ideator (`IDEATOR_MODEL`, default `claude-opus-5-5` on Vertex, thinking
  set explicitly; **open**, configurable) gets the trial's task, model, trace,
  and the evidence items below.
- Method A contributes `A:failing_step` (pointer `trace#step=N`, or
  `credit_a.jsonl#<trial>#step=N`).
- Method B, when `status` is `ok`, contributes `B:window` and one `B:step:<n>`
  per labelled step (pointer `credit_b.jsonl#<trial>#step=<n>`). A short
  window is included as it is; `method_b_window_length` is that length.
- When Method B's `status` is `empty_window` (the failure is at step 1, so
  there is no prior step), the ideator input contains only Method A's
  evidence. The proposal row records `method_b_status: empty_window` and
  `ideator_evidence: ["A"]`. The B credit row is still listed in `credit_rows`.
  `empty_trace` and `judge_error` also contribute no B item; the row records
  that status.
- It must return **exactly 5** alternatives. A wrong count, any invalid patch,
  or a missing citation gets one re-ask with the reasons.
- Each alternative cites the evidence it uses: `citations` is a non-empty
  list of `{method: A|B|both, evidence: <id or [ids]>}`. `A` or `B` names one
  id of that method. `both` names one A id and one B id. The stored citation
  keeps the pointer. An alternative with no citation is `rejected`,
  `uncited: true`, and is not run.
- Each row records:
  - `prompt_version` (`I2` for a drawn failure, `I1` for a single-method call) and `ideator_model`;
  - `parent_trial_id`, `task`, `model`;
  - **`credit_method`** and `credit_rows` (pointers into `credit_a.jsonl` / `credit_b.jsonl`);
  - `ideator_evidence` (`["A", "B"]` or `["A"]`), `method_b_status`, `method_b_window_length`;
  - `citations` (each with `method`, `evidence`, and `pointer`) and `uncited`;
  - `rationale`, `patch` and `proposal_id` (a hash of the patch);
  - `status` (`accepted` or `rejected`), `rejection_reasons` and `complete_set`;
  - the raw ideator output and its usage.

## Evaluation: selection, then confirmation (`ideation_results.jsonl`)

Two stages (João Sedoc via Sean, SEA-110). `evaluate(run_dir, proposal, executor)` runs both.
The cell is evaluated when the fresh baseline's `set_aside` count is at most
`max_set_aside` (default **3**, about 10% of 30), the same cap as credit
assignment. `evaluate(..., max_set_aside=n)` overrides the default.

The selection baseline is the fresh baseline in `credit_baseline.json` (see
`CREDIT_ASSIGNMENT.md`), not the pilot `summary.jsonl` row. A cell with no
fresh baseline raises. There is no fallback. `summary_row_baseline` raises if
called.

1. **Selection.** The alternative runs **N = 30** trials on the parent's task
   and model, with its patch (`ideation/<proposal_id>/select/`). It is a
   **candidate** iff both it and the fresh baseline completed all N trials
   and it has **more passes** (`decide`: a bare beat, no significance gate).
   **1/30 vs 0/30 qualifies. A tie does not.**
2. **Confirmation (candidates only).** A **fresh** N-trial run of the
   alternative (`.../confirm/`) **and** a **new** N-trial baseline run with
   no patch (`.../confirm-baseline/`). Each arm has its own run id, so its
   trial ids are new. The confirmation baseline is that new run, not the
   selection baseline and not the pilot summary. OpenCode has no sampling
   seed: every trial is an independent sample. **`success`** iff the
   alternative beats the new baseline: full N on both sides, more passes.

   **`confirm`** chooses which candidates are confirmed. The default is
   `all`: every selection candidate, which is the behaviour above. `top`
   confirms `confirm_k` candidates per cell `(model, task)`. `confirm_k`
   defaults to 1. The pool is every accepted alternative of that cell's drawn
   failures (`credit_draw.json`, status `IN`), and the choice waits until
   each of those failures has a proposal row and every accepted proposal has
   a selection row. Until then the cell stays unconfirmed (`confirmed` null,
   `confirm_skipped` null). The ranking is most `selection_alt_passes`, then
   the earlier seeded pick (`draw_order`), then the lower `alternative_index`
   (the proposal's `index`), then `proposal_id`. Fisher p is not a tie-break:
   the cell shares one baseline, so the same pass count is the same p. A cell
   with fewer than `confirm_k` candidates confirms all of them. The others
   stay candidates, with `confirm_skipped` `not_top` and confirmation fields
   null. Each confirmed candidate gets its own fresh N-trial alternative and
   its own fresh N-trial baseline, keyed by `(parent_trial_id, proposal_id)`,
   including when two failures share a patch. Eight cells at `confirm_k` 1
   are eight confirmations. `confirm` and `confirm_k` are stored on every
   result row, and a `top` row records `draw_order`. `confirm_k` must be an
   integer >= 1. A value other than 1 is an error when `confirm` is `all`.
   Each confirmed candidate is written to `ideation_results.jsonl` as soon as
   its confirmation finishes. A later confirmation that raises leaves those
   rows in the file, and the confirmations after it do not start.

   An arm directory is `ideation/<proposal_id>/<label>`, with the parent trial
   id added only when one cell confirms the same patch more than once. Before
   the arm runs, an existing `plan.json` whose model, task, or `parent_trial_id`
   belongs to a different arm is an error. The directory is not overwritten. The
   same arm run again resumes. Selection of one patch on the same model and task
   stays one directory across that cell's failures, which is the `confirm_k` 1
   layout.

```text
python3 -m obench.reflection.ideation --run <run dir> --fixture passes.json [--config ideation.json] [--confirm top|all] [--confirm-k K]
```

`--config` is an `IdeationConfig` JSON object (`{"confirm": "top", "confirm_k": 3}`
or `"all"`). `--confirm` and `--confirm-k` override the file. The default is
`confirm=all` and `confirm_k=1`. `evaluate(..., confirm="top"|"all", confirm_k=1)`
is the same setting. That command's only executor is the offline `--fixture`
pass table. It does not start a provider. The command prints `confirm` and
`confirm_k` with the run counts.

Every arm runs through the SEA-107 runner in `fixed_tasks` mode: exactly the
parent's task (even a pool task), never a suite swap. Each arm, including the
confirmation baseline, reuses the fresh baseline's recorded image
(`recorded_image`: ref, id, and `image_matches_pin`) and runs with smoke
compaction off. A trial that reports a different image is refused. The image
is not re-pinned.

Every arm row records `code_commit`: the fresh baseline manifest, and the
selection, confirmation, and confirmation-baseline summaries. `evaluate`
refuses (raises, and does not write a result row) when any arm's
`code_commit` differs from the fresh baseline's `baseline_commit`. The fresh
baseline's own `code_commit` must equal `baseline_commit`.

**Columns, one row per evaluated proposal:**

| Stage | Columns |
|---|---|
| Selection | `selection_baseline_passes`, `selection_baseline_completed`, `selection_alt_passes`, `selection_alt_completed`, `selection_beats_baseline`, `selection_complete`, `selection_fisher_p`, `candidate`, `selection_spend_usd`, `selection_run_dir`, `selection_run_state`, `selection_code_commit` |
| Confirmation | `confirmation_baseline_passes`, `confirmation_baseline_completed`, `confirmation_alt_passes`, `confirmation_alt_completed`, `confirmation_beats_baseline`, `confirmation_complete`, `confirmation_fisher_p`, `confirmed`, `confirmation_spend_usd`, `confirmation_run_dirs`, `confirmation_run_states`, `confirmation_code_commit`, `confirmation_baseline_code_commit`. All null for non-candidates and for candidates skipped under `confirm=top`. |
| Outcome | `success` (= `confirmed`), `confirm` (`all` or `top`, on every row), `confirm_k` (on every row; default 1), `confirm_skipped` (`not_top` when a candidate in the cell was outside the confirmed set; otherwise null), `alternative_index`, `draw_order` (the seeded pick, set under `top`; null under `all`), `credit_method`, `parent_trial_id`, `task`, `model`, `n_trials`, `alpha`, `baseline_commit`, `code_commit`, `citations`, `uncited` |

`alpha` is the value `evaluate` used. It is always `1.0`. `evaluate` has no
`alpha` parameter and refuses to write a row whose alpha is not 1.0.
`baseline_commit` is the fresh baseline's checkout.

`*_fisher_p` is the one-sided Fisher exact p for that stage, **reported only,
never a gate**. A higher pass count is a candidate even when that p is above
0.10. `decide(alpha=...)` can still apply a gate for a library check.
`evaluate` does not. A p-gated reading belongs only in a report, as a separate
sensitivity column computed from the recorded Fisher p. It does not change
`candidate`, `confirmed`, or `success`.

## Cost

`runner.ideation_estimate(executor, {model: failures}, n_alternatives=5,
n_trials=30, candidate_fraction=1.0, confirm="all", cells=None, confirm_k=1)`:
- selection costs `failures × 5 × 30` trials either way;
- `confirm=all` adds `failures × 5 × candidate_fraction × (30 + 30)` trials
  (every candidate: the fresh alternative plus the fresh baseline);
- `confirm=top` adds `cells × confirm_k × (30 + 30)` trials. `cells` is
  `{model: cell count}` and is required. `confirm_k` defaults to 1, so one
  cell is one confirmation, however many drawn failures it holds.
  `candidate_fraction` does not change that count.

The worst case for `confirm=all` (`candidate_fraction = 1`) is 3× the
selection cost. For example, one failure at Opus's provisional $2/trial costs
$300 to select and up to $600 more to confirm. Three failures in one cell at
`confirm=top` and `confirm_k` 1 still cost $900 to select and $120 to confirm
($1020). `confirm_k` 3 on that cell costs $360 to confirm. Eight cells at
`confirm_k` 1 are eight confirmations ($960 at $2/trial). The estimate records
`confirm`, `confirm_k`, and `cells`.
