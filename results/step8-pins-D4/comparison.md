# Step-8 D4 nearest-build pin validation (2026-10-26)

**Result: FAILED. Check (a) has one differing PR, and check (b)'s misses land on versions that step-8 cells have failed on. Per D4 rule 3, no pins were written, no proposed table was made, and nothing is spent until Sean decides.**

## Definition of "nearest" (D4 rule 2)
- Position = index on the OpenCode first-parent history of `origin/dev` (mirror tip `bc5ebf00`), oldest = 0 (`git rev-list --first-parent --reverse`).
- A sha off that line goes to the first first-parent commit that contains it. All 116 box sides were on the line already.
- distance = |pos(a) − pos(b)|. Ties go to the earlier (lower-position) build, then to the lower sha.
- A new PR's pin is the nearest box build to its without (parent) side, applied to both sides.
- "Failed" means a step-8 cell with `failure_class` infra or a `provider_pin_mismatch` error (`failed_versions.csv`).

## (a) Within-PR check: 56 of 57 box PRs had the same version on both sides
- Differs: **PR 1443**. with `18888351` = 2.0.0-beta.13, without `3b7085ca` = 2.0.0-beta.11.

## (b) Leave-one-out over 116 box_cache sides
| variant | agree | rate | misses | misses on a failed version |
|---|---|---|---|---|
| leave-own-sha-out (as briefed) | 114/116 | 98.3% | 2 | 2 |
| leave-own-PR-out (how new PRs are pinned) | 113/116 | 97.4% | 3 | 3 |

- The rate clears 95% in both variants. The second condition fails: every predicted version on a miss has infra failures on record.
- Leave-own-sha-out misses: both sides of PR 1443, each predicted from the other side (beta.11 ↔ beta.13).
- Leave-own-PR-out misses:
  - 1443 with: predicted beta.11, from `541a7a39` at distance 87.
  - 40990 both sides: actual 3.0.71, predicted 3.0.64 from `aacdb34e` at distance about 1300.
- Failed versions: 2.0.0 infra 3, beta.11 infra 4, beta.13 infra 5, 3.0.64 infra 1, 3.0.71 infra 2. Also 25 `provider_pin_mismatch: empty cache` cells (version "missing") in the VM F03-1 pinned run, and 7 quarantined VM cells with no version.
- Only 1.2.12 has no infra failures, so as written the condition can only be met by a miss that predicts 1.2.12.
- Most of these infra errors are `no_progress` idles or connection timeouts, not provider faults. Whether they should count is a call for the Researcher or Sean.

## F16-2 and D4 rule 4
See `f16-2.md`.

Reproduce: `python3 thesis/ab/derive_nearest_build_pins.py validate --mirror <opencode mirror> --out-dir results/step8-pins-D4 --subs SUBS.txt --prs prs.csv` (exit 1). Files: `comparison.csv` (per side: pos, both variants' pin_from, dist, pred, match, failures on pred), `within_pr.csv`, `failed_versions.csv`.
