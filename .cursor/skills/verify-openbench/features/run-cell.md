# run_cell

`thesis.ab.run_ab.execute_cell` is the A/B runner's single-cell entry. It loads the harness adapter and calls `obench.run.run_cell`, which stages the task, runs the adapter, and runs the checker. The cell file is `results/<out>/<pr>/cells/<side>/<task>/<trial>.json`.

## Sub-features

- Plan a cell without launching it (`--dry-run`).
- Record `runner_commit` from `RUNNER_SHA` / `OBENCH_RUNNER_COMMIT` / `git rev-parse` when `--cell-meta` is set.
- Stop launching once finished cells reach `--max-cost-usd` (`over_budget`). The stub for that stop is in the step-8 gate feature.
- Built-in `null` harness: `obench legacy run --harness null` exercises `run_cell` with an adapter that does not edit the workspace and does not call a model. The checker must fail. That is the negative control, not an A/B comparison.

## How to get to it (user POV)

From the repo root, print the cells the runner would launch for one trigger task:

```bash
python3 -m thesis.ab.run_ab thesis/ab/fixtures/opencode-harness-prs.csv \
  --pr 4204 \
  --task trig-subagent-followup \
  --task-map thesis/ab/fixtures/trigger-tasks.csv \
  --trials 1 \
  --dry-run
```

A real cell (model spend, not a stub) is the same command without `--dry-run`. It needs a built OpenCode binary, `GOOGLE_CLOUD_PROJECT`, and application-default credentials. The shared proxy listens locally and forwards to Vertex. Do not point it at `api.anthropic.com`.

## Driving it with verify-openbench

1. Doctor must already show `thesis` and `obench` loaded from this checkout, and `resolve_runner_commit` equal to `HEAD`.
2. Run the dry-run with the key variables removed:

```bash
env -u ANTHROPIC_API_KEY -u ANTHROPIC_BASE_URL -u OPENAI_API_KEY \
    -u GOOGLE_APPLICATION_CREDENTIALS -u GOOGLE_CLOUD_PROJECT -u GCLOUD_PROJECT \
  python3 -m thesis.ab.run_ab thesis/ab/fixtures/opencode-harness-prs.csv \
    --pr 4204 \
    --task trig-subagent-followup \
    --task-map thesis/ab/fixtures/trigger-tasks.csv \
    --trials 1 \
    --dry-run
```

3. Save stdout in `results/verify-openbench/<date>/dry-run.txt`. Pass is exit 0 and these lines:

```
4204 without 0d3d48bb5964a95e939edcea3bb726a21823d1a1 with 963a926db24ea70f6002cde66d0ff858de06fae2 tasks trig-subagent-followup
trials: 1
cells: 2
order: sides
```

4. Confirm the process exited and no proxy or Docker container is left behind. The command does not write a cell file.

The matching unit test is `obench.tests.test_ab` (it calls `drive(..., dry_run=True)`).

## Gotchas

- `--dry-run` does not call `execute_cell` or `run_cell`. It only prints the plan. A green plan does not mean a checker ran.
- `--trials 1` is two cells (without and with). The README's five-trial example is ten cells.
- `pip install -e .` does not install `thesis`. Run from the repo root so the import is this tree.
- Do not set `OBENCH_RUNNER_COMMIT` to a SHA other than this checkout and then treat the dry-run as proof of that pin. The dry-run does not record `runner_commit`.
