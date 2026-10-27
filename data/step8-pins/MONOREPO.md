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
| `monorepo-dry-run.csv` | `thesis.ab.step8_pin_dry_run --monorepo-only` | the six sides: ready/not-ready with a reason, `bundled_provider`, `score_match`, `scorable` |
| `monorepo-smoke.csv` | `thesis.ab.step8_monorepo_smoke` | one smoke cell per side: provider faults, the agent's call, loaded source, bundled version, smoke and box scoring calls, `score_match`, `scorable` |

As committed, nothing has been built and no smoke has run. `monorepo-builds.csv` holds the source commit and lockfile sha256 from the mirror (`used=no`, "not built; control step not run"). `monorepo-dry-run.csv` shows all six sides not ready (binary missing) and not scorable.

## Build rule and control step

Binaries are built the same way as F03-2: the runner's `build_opencode` (shared mirror, `<opencode-src>/worktrees/<sha>`, the bun version the tree asks for, `<opencode-src>/bin/<sha>/opencode`).

Before any rebuilt binary is used, three step-8 builds that already have a binary are rebuilt into `<opencode-src>/control-rebuild`, leaving the existing binaries untouched. The defaults are the newest pinned sides with a binary; `--control SHA[:SIDE]` overrides them. Each rebuild must match its existing build on `opencode --version` and on the provider it loads (strace `openat` of `node_modules/@ai-sdk/anthropic` against the side's pinned cache). A check that cannot run counts as a mismatch. If any control does not match, the step exits 3, the six sides are not built, and every record is `used=no`.

A monorepo side is ready only when `monorepo-builds.csv` shows all three controls matched and a `used=yes` record whose `binary_sha256` equals the binary on disk. The smoke refuses to launch otherwise.

## Scoring rule (D5 §4)

- The smoke cell's scoring call is `pass` (`failure_class=solved`) or `fail` (any other scored class). Infra has no scoring call.
- The box's scoring call is the majority of its scored cells for the same PR, side and task, as recorded on main (`results/step8-full413-1020*` and `results/step8-sonnet447-pilot-1020-full`). A tie is `fail`.
- `score_match` is `true` only when both calls exist and are equal. Missing box data, or box cells that are all infra, is `false`.
- A side is `scorable` only when it is ready, its smoke cell loaded the bundled provider with zero provider faults (D4 rule), and `score_match=true`. The dry run recomputes this from `smoke_score` and `box_score`.

Main has no box cells for these three PRs, so as things stand every side is `score_match=false` and would be reported as excluded.

## Commands (machine with existing step-8 builds)

```bash
python3 -m thesis.ab.step8_monorepo_smoke --cache <opencode-src> --plan          # no model call
python3 -m thesis.ab.step8_monorepo_build --cache <opencode-src>                 # control step, then build + records
python3 -m thesis.ab.step8_pin_dry_run --monorepo-only --bin-root <opencode-src> --mirror <opencode-mirror>
python3 -m thesis.ab.step8_monorepo_smoke --cache <opencode-src> --out results/step8-monorepo-smoke-<date>   # 6 model-backed cells
python3 -m thesis.ab.step8_pin_dry_run --monorepo-only --bin-root <opencode-src> --mirror <opencode-mirror>  # picks up the smoke
```
