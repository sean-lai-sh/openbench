# Proof: verify-openbench 2026-11-12

Feature driven end to end: OpenCode `--model claude-sonnet-5-5` on the existing proxy route (`obench.adapters.opencode` and `thesis.ab.run_ab`), then the scoring replay. No model call. API key variables were unset. Nothing contacted `api.anthropic.com`.

## Doctor

- Python 3.12.3
- `thesis` loaded from `/agent/repos/openbench/thesis/__init__.py` (this checkout, not site-packages)
- `obench` loaded from `/agent/repos/openbench/obench/__init__.py` after `pip install -e .`
- `resolve_runner_commit` = `HEAD` = `39875fac6670b24c1cef2635aaf077e5c6e04741` (main at verification time; the Sonnet change was in the working tree)
- `RUNNER_SHA` unset
- `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, `OPENAI_API_KEY`, `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CLOUD_PROJECT`, `GCLOUD_PROJECT` all unset
- `thesis/ab/launchers/egress_block.sh` present and not applied

## OpenCode model

`--model claude-sonnet-5-5` is accepted. With `OBENCH_OPENCODE_PROXY` set to the historical Opus `model_ref`, the cell still takes the proxy route (dummy key, base URL, experimental models on, no `VERTEX_LOCATION`) and `opencode run -m` is `anthropic/claude-sonnet-5-5`.

`--model claude-opus-5-5` keeps `model_ref` verbatim, including a Sonnet ref. `--vertex-model claude-sonnet-5-5` with the default model still records Opus and serves Sonnet. `--model claude-sonnet-5-5 --vertex-model claude-sonnet-5-5` records Sonnet on the row, the config model id, `model_ref`, and the Vertex protocol model.

Stub plans for those three flag combinations exit 0 with `cells: 2`. No cell was launched.

## Scoring replay

`python3 -m thesis.ab.step8_scoring_parity --out results/verify-openbench/2026-11-12/scoring-parity.csv`

Exit 0.

```
scoring_parity pass: 180/180 cells
  step8-full413-1020-F01 579: 60/60 cells match on call and class (box pass 0, fail 60; hang=60)
  step8-full413-1020-F03-1-rerun 3006: 60/60 cells match on call and class (box pass 60, fail 0; solved=60)
  step8-full413-1020-F03-1-rerun 3079: 60/60 cells match on call and class (box pass 60, fail 0; solved=60)
```

CSV: 181 lines (header + 180). The committed `data/step8-pins/scoring-parity.csv` was not rewritten.

## Summarize

`python3 -m thesis.ab.summarize results/step8-full413-1020/prs.csv --results results/step8-full413-1020-F03-1-rerun --out results/verify-openbench/2026-11-12/summary`

Exit 0. Wrote `summary.md` and `summary.csv`.

## Launch dry-run

Exit 0. Plan is `cells: 2`, `order: sides`, PR 4204, task `trig-subagent-followup`. No `run_cell` execution.

## Tests

Focused thesis modules plus `obench.tests.test_opencode_vertex`: 160 tests, OK.
Full `python3 -m unittest discover -s obench/tests`: 2336 tests, 1 failure and 81 errors, all from the publish PII check on hostname `cursor`.
