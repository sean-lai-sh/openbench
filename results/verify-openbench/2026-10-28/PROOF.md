# Proof: verify-openbench 2026-10-28

Feature driven end to end: scoring (`thesis.ab.step8_scoring_parity`, then `thesis.ab.summarize`). No model call. API key variables were unset. Nothing contacted `api.anthropic.com`.

## Doctor

- Python 3.12.3
- `thesis` loaded from `/workspace/thesis/__init__.py` (this checkout, not site-packages, not `~/ob-f032`)
- `obench` loaded from `/workspace/obench/__init__.py` after `pip install -e .`
- `resolve_runner_commit` = `HEAD` = `d9ddb04806cbe465cfb1b5ff35ed8d69326cd97a`
- `RUNNER_SHA` unset (stub checkout; a live `step8_f032.sh` launch must set it to that checkout's HEAD)
- `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, `OPENAI_API_KEY`, `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CLOUD_PROJECT`, `GCLOUD_PROJECT` all unset
- `thesis/ab/launchers/egress_block.sh` present and not applied

## Scoring replay

`python3 -m thesis.ab.step8_scoring_parity --out results/verify-openbench/2026-10-28/scoring-parity.csv`

Exit 0.

```
scoring_parity pass: 180/180 cells
  step8-full413-1020-F01 579: 60/60 cells match on call and class (box pass 0, fail 60; hang=60)
  step8-full413-1020-F03-1-rerun 3006: 60/60 cells match on call and class (box pass 60, fail 0; solved=60)
  step8-full413-1020-F03-1-rerun 3079: 60/60 cells match on call and class (box pass 60, fail 0; solved=60)
```

CSV: 181 lines (header + 180). The committed `data/step8-pins/scoring-parity.csv` was not rewritten.

## Summarize

`python3 -m thesis.ab.summarize results/step8-full413-1020/prs.csv --results results/step8-full413-1020-F03-1-rerun --out results/verify-openbench/2026-10-28/summary`

Exit 0. Wrote `summary.md` and `summary.csv`. Recorded PRs 3006 and 3079 show delta score 0.000 on one paired task each. PR 579 is in the parity replay only; this results dir does not hold its cells, so the summary leaves it blank.

## Launch dry-run

Exit 0. Plan is `cells: 2`, `order: sides`, PR 4204, task `trig-subagent-followup`. No `run_cell` execution.

## Tests

Focused thesis modules: 162 tests, OK.
Full `python3 -m unittest discover -s obench/tests`: 1983 tests, 1 failure and 81 errors, all from the publish PII check on hostname `cursor`.
