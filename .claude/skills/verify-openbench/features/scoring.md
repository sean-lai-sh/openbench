# Scoring

Scoring replays saved cell output through this checkout's checker path and summarizes recorded A/B sides. It does not call a model, re-run the checker, or talk to GCP.

## Sub-features

- `python3 -m thesis.ab.step8_scoring_parity` replays each saved cell the way `obench.run.run_cell` and then `run_ab.execute_cell` score it: drop the box verdict, parse `checker_stdout`, apply the explicit-verdict or exit-code rule, then `apply_watchdog_class`. Pass requires the replayed pass/fail and `failure_class` to match the box on every cell.
- Default inputs are 180 cells. `results/step8-full413-1020-F03-1-rerun` PRs 3006 (`make-it-run`) and 3079 (`taskflow`) are 120 solved cells. `results/step8-full413-1020-F01` PR 579 (`trig-read-lines`) is 60 `hang` cells.
- `python3 -m thesis.ab.summarize` writes `summary.md` and `summary.csv` for a recorded results directory. Warm-up cells count unless you pass `--exclude-warm-up`.

## How to get to it (user POV)

Replay the committed box cells:

```bash
python3 -m thesis.ab.step8_scoring_parity --out results/verify-openbench/<date>/scoring-parity.csv
```

Summarize the same F03-1 rerun batch (the PR list is the recorded step-8 table; missing PR directories contribute no rows):

```bash
python3 -m thesis.ab.summarize results/step8-full413-1020/prs.csv \
  --results results/step8-full413-1020-F03-1-rerun \
  --out results/verify-openbench/<date>/summary
```

The default `--out` of the parity command is `data/step8-pins/scoring-parity.csv`. Point a verification run at the evidence directory instead.

## Driving it with verify-openbench

1. Confirm the three side files exist: `results/step8-full413-1020-F03-1-rerun/3006/without.jsonl`, `.../3079/with.jsonl`, and `results/step8-full413-1020-F01/579/without.jsonl` (and their sibling sides). Each default side file is 30 lines.
2. Run parity with keys removed:

```bash
env -u ANTHROPIC_API_KEY -u ANTHROPIC_BASE_URL -u OPENAI_API_KEY \
    -u GOOGLE_APPLICATION_CREDENTIALS -u GOOGLE_CLOUD_PROJECT -u GCLOUD_PROJECT \
  python3 -m thesis.ab.step8_scoring_parity \
    --out results/verify-openbench/<date>/scoring-parity.csv
```

3. Pass is exit 0 and stdout containing `scoring_parity pass: 180/180 cells`. The F01 block is `box pass 0, fail 60; hang=60`. The two F03-1 PRs are `box pass 60, fail 0; solved=60`. The CSV has a header plus 180 rows.
4. Run the summarize command above. Pass is exit 0 and both `summary.md` and `summary.csv` in the `--out` directory. The report is a reading of saved rows, not a new trial.

## Gotchas

- Omitting `--out` overwrites the committed parity table. Do not commit that rewrite from a verification run.
- Exit code 3 means parity failed. The `match` column in an old CSV is not trusted; the command recomputes call and class.
- PR 579 without trial 27 is relabeled infra only in `overrides.csv`. The saved row the replay reads still says `hang`.
- Summarize on `results/step8-full413-1020-F03-1-rerun` does not include the F01 hang cells. Those are only in the parity replay.
- A transcript under `results/` is local evidence. It is not the score. The score is `failure_class` on the cell row.
