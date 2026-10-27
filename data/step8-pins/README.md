# Step-8 nearest-box provider pins (F03-2 through F16)

Both sides of each PR use one `@ai-sdk/anthropic` version: the version a box-run OpenCode build left in its cache, chosen as the build nearest the without (parent) commit. That is the nearest-box method, the same rule as the F03-1 pinned rerun (the version shipped in the OpenCode build closest to the PR). The seven F03-1 sides stay `vm_quarantine_log` / `2.0.0` and are not rewritten. `pin_from` is the source build.

## D4 decision

Count provider faults only as infra. Timeouts, install errors, auth errors, and `provider_pin_mismatch: empty cache` do not disqualify a version and do not change a pass rate.

The #155 rescore is unchanged (`results/step8-full413-1020-F01/rescore-provider-faults/`): 1545 without trig-lsp-ts trial 22 is excluded from the pass rate as infra; 579 without trig-read-lines trial 27 is relabeled infra only (`label_only`) and stays in the denominator as a hang. Pass-rate formulas are not edited.

Under that decision the D4 gate can be used:

- Within-PR: box sides that differ are 1443. PR 1443 is not rewritten. Its single-version rerun is `rerun-1443.json` (not launched).
- Leave-one-out (drop the sha): 114/116 agree. Misses: 2, predicted 2.0.0-beta.11, 2.0.0-beta.13. Misses on a version with a provider fault: 0.
- Leave-one-PR-out (how a new PR is pinned): 113/116 agree. Misses: 3, predicted 2.0.0-beta.11, 3.0.64. Misses on a version with a provider fault: 0.
- Provider-fault cells on a recorded version: none. The F01 cell 579 without trig-read-lines trial 27 logs `TimeoutError` plus the words `stream error`. #155 kept that cell as a hang (`label_only`). It is a timeout, not a provider fault, and it does not disqualify `1.2.12`.

Leave-one-out agreement is 114/116 (98.3%). Apply exits nonzero when that rate is below 95%. No miss predicts a version that has a provider fault. The earlier infra-only reading of the same misses is in `results/step8-pins-D4/` and is not the rule these pins use.

## What was pinned

Queue: `results/step8-vm-F03-1-1025-QUARANTINED/SUBS.txt` from `F03-2` through `F16-2`, SHAs from `results/step8-full413-1020/prs.csv`. OpenCode first-parent line of `origin/dev` at `0ed012cb2ef34d7937c22969bdc062eb32476341` (15531 commits). Box candidates: 111 builds, 116 box_cache sides.

| | count |
|---|---|
| pinned sides | 586 |
| pinned PRs | 293 |
| deferred sides | 6 |
| unpinned sides | 0 |

| @ai-sdk/anthropic | sides |
|---|---|
| 2.0.0 | 220 |
| 3.0.64 | 320 |
| 3.0.71 | 46 |

Every pinned PR has the same version on both sides. No pinned SHA is already a box_cache or F03-1 entry. Historical pins, including PR 1443 (`2.0.0-beta.13` on the merge, `2.0.0-beta.11` on the parent), are left as recorded.

## Deferred (not this PR)

Post-monorepo runner work for **51062**, **53166**, and **55613** is excluded. Each side has no `packages/opencode` (`51062` `328f74c2` / `32b1a1bf`, `53166` `0cb43477` / `bcf23b67`, `55613` `ae8d59f8` / `7ced591c`). They are `status=deferred` in `pins.csv` and have no `provider_pins.json` entry.

## PR 1443 rerun (do not run)

`rerun-1443.json` pins both sides to `2.0.0-beta.11`. That is the parent side's own box version, which is the nearest box build to the parent at distance 0. Leave-one-PR-out predicts the same version for the merge side. F01 spent $4.27 on 60 cells (30 trials, both sides). A 30-trial rerun is estimated at about $5–6. This PR does not launch it.

## Reproduce

```bash
python3 -m thesis.ab.step8_pins apply --mirror <opencode-mirror>
python3 -m thesis.ab.step8_pin_dry_run --cache /tmp/step8-pin-cache --bin-root <opencode-src>
```

`<opencode-src>` is the directory of built OpenCode binaries. The dry run reads `<opencode-src>/bin/<sha>/opencode` (`--bin-root`). `apply` rewrites this directory (`data/step8-pins/`) and merges new sides into `thesis/ab/provider_pins.json`. It does not call a model. The dry run seeds `<cache>/seed-cells/<version>` and writes `dry-run.csv` and `dry-run.md` here. Strace homes stay under `--cache` and are not committed.
