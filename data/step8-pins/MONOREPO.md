# Step-8 post-monorepo sides (51062, 53166, 55613)

Runner notes for the six sides that #160 deferred. `pins.csv`, `provider_pins.json`, `rerun-1443.json`, `dry-run.csv`, `dry-run.md` and `README.md` in this directory come from #160 and are not changed by the runner PR. In `pins.csv` the six sides stay `status=deferred` because there is nothing to pin.

| PR | with | without | bundled provider | `bun.lock` sha256 |
|---|---|---|---|---|
| 51062 | `328f74c2` | `32b1a1bf` | `@opencode/ai@2.0.29`, `packages/ai/src` tree `0081539dc8aa` | `e5df36a41694…` |
| 53166 | `0cb43477` | `bcf23b67` | `@opencode/ai@2.0.27`, tree `9022f537f155` | `4b82f2e166d2…` |
| 55613 | `ae8d59f8` | `7ced591c` | `@opencode/ai@2.0.29`, tree `0081539dc8aa` | `e5df36a41694…` |

## Why there is no pin

These commits have no `packages/opencode`. The CLI builds from `packages/cli` (`script/build.ts --single`, output `packages/cli/dist/cli-<os>-<arch>/bin/opencode`). The Anthropic provider is OpenCode's own `packages/ai` (`@opencode/ai`, `src/providers/anthropic.ts`), compiled into the binary. `bun.lock` has no `@ai-sdk/anthropic`. Both sides of each PR have the same `packages/ai/src` tree and the same lockfile, so neither is part of the with/without difference.

Cells run provider-free (`thesis/ab/monorepo.py`). Nothing is seeded, `anthropic_sdk` and `provider_pins` are dropped, and the `needs_sdk` preflight is skipped. Each cell records `provider_loaded_source`, `bundled_provider_package`, `bundled_provider_version`, `bundled_provider_tree` and `pin_source=bundled_monorepo`. #156's runtime probe value is kept as `provider_loaded_probe`. If nothing was loaded, the source is `bundled`. A traced `@ai-sdk/anthropic` load is `separate_install`, and the cell is infra (`provider_bundled_mismatch`).

## Tables in this directory

| file | written by | what |
|---|---|---|
| `monorepo-builds.csv` | `thesis.ab.step8_monorepo_build` | one build record per binary: source commit, worktree `HEAD`, build plan, bun version, lockfile sha256, binary sha256, reported build info, loaded provider. Control rows add the existing build's values plus `control_match` and `control_status`. |
| `dry-run-monorepo.csv` | `thesis.ab.step8_pin_dry_run` (full run or `--monorepo-only`) | one row per side, keyed by `side_key` (`<pr>:<side>`). It has #160's dry-run columns plus `provider_mode`, `bundled_provider`, `scoring_parity` and `scorable`. `dry-run.csv` keeps #160's format, with the six sides `deferred`. |
| `scoring-parity.csv` | `thesis.ab.step8_scoring_parity` | one row per replayed box cell: box and replayed `failure_class`, box and replayed pass/fail call, `call_match`, `class_match`, `match` |
| `monorepo-smoke.csv` | `thesis.ab.step8_monorepo_smoke` | one smoke cell per side: provider faults, the agent's call, loaded source, bundled version, `smoke_ok`, `scoring_parity`, `scorable` |

As committed, nothing has been built and no smoke has run. `monorepo-builds.csv` holds the source commit and lockfile sha256 from the mirror (`used=no`, "not built; control step not run"). `scoring-parity.csv` passes: 180/180 cells (3006, 3079, 579) agree on pass/fail and on `failure_class`. `dry-run-monorepo.csv` shows all six sides not ready (binary missing), `scoring_parity=pass`, and `scorable=excluded`.

## Build rule and control step

Binaries are built the same way as F03-2: the runner's `build_opencode` (shared mirror, `<opencode-src>/worktrees/<sha>`, the bun version the tree asks for, `<opencode-src>/bin/<sha>/opencode`).

Before any rebuilt binary is used, three step-8 builds that already have a binary are rebuilt into `<opencode-src>/control-rebuild`, leaving the existing binaries untouched. The defaults are the newest pinned sides with a binary; `--control SHA[:SIDE]` overrides them. Each rebuild must match its existing build on `opencode --version` and on the provider it loads (strace `openat` of `node_modules/@ai-sdk/anthropic` against the side's pinned cache). A check that cannot run counts as a mismatch. If any control does not match, the step exits 3, the six sides are not built, and every record is `used=no`.

A monorepo side is ready only when `monorepo-builds.csv` shows all three controls matched and a `used=yes` record whose `binary_sha256` equals the binary on disk. The smoke refuses to launch otherwise.

## Scoring rule (D5 §4)

The three PRs are scorable together or not at all. All of the following must hold, or every side is `scorable=excluded`:

- every side is ready (see the build rule above), and
- all six smoke cells exist, loaded the bundled provider (`provider_loaded_source=bundled`), and have zero provider faults (D4 rule), and
- `scoring_parity` passes.

`scoring_parity` checks that this runner scores like the box on PRs the box already ran. It replays the box's saved outputs for every cell of three PRs:

- **3006** (`make-it-run`) and **3079** (`taskflow`) from `results/step8-full413-1020-F03-1-rerun`. This is the latest batch the box scored; its `RERUN.txt` lists 2986, 3006 and 3079 as complete (3185 is partial and unscored), and these are the last two complete ones. 120 cells, all `solved`.
- **579** (`trig-read-lines`) from `results/step8-full413-1020-F01`. It went 0/30 on both sides: 60 cells, all `hang`, with the no-progress watchdog firing after model requests while the checker passed the workspace. This adds fails, and it exercises the watchdog step. 579 without trial 27 is relabeled infra by the #155 rescore only in `overrides.csv` (`label_only`); its saved row, which is what the box recorded, says `hang`.

Each cell goes through the runner's scoring path, in the order `obench.run.run_cell` and then `run_ab.execute_cell` apply it:
1. Drop the box's verdict fields.
2. Parse `SCORE:` from the saved `checker_stdout`.
3. Apply `apply_explicit_verdict` (thesis tasks) or the exit-code rule, then `classify_failure`.
4. Apply `thesis.ab.watch.apply_watchdog_class`.

The replayed pass/fail (`solved` = pass) **and** `failure_class` must equal the box's on 100% of cells, and the table must have exactly those three PRs and 180 cells. It uses saved outputs only: no model calls and no checker re-run. Today it reproduces **180/180** (120 pass, 60 fail). Step 4 matters: without it, 579's cells would replay as 59 `solved` and 1 `wrong_answer`.

`step8_pin_dry_run` recomputes all of this from `monorepo-smoke.csv` (counts, not the `smoke_ok`/`scorable` columns) and `scoring-parity.csv` (calls and classes, not the `match` columns).

## Commands (machine with existing step-8 builds)

```bash
python3 -m thesis.ab.step8_scoring_parity                                        # no model call; writes scoring-parity.csv
python3 -m thesis.ab.step8_monorepo_smoke --cache <opencode-src> --plan          # no model call
python3 -m thesis.ab.step8_monorepo_build --cache <opencode-src>                 # control step, then build + records
python3 -m thesis.ab.step8_pin_dry_run --monorepo-only --bin-root <opencode-src> --mirror <opencode-mirror>
python3 -m thesis.ab.step8_monorepo_smoke --cache <opencode-src> --out results/step8-monorepo-smoke-<date>   # 6 model-backed cells
python3 -m thesis.ab.step8_pin_dry_run --monorepo-only --bin-root <opencode-src> --mirror <opencode-mirror>  # picks up the smoke
```
