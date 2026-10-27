# Step-8 pin dry run

No model calls and no GCP. Each F03-2..F16 side and both sides of `rerun-1443.json` were loaded. Pins were resolved from `provider_pins.json` (the 1443 rerun uses the single version in that config). The shared cache was seeded once per version with `bun add --exact` under `<cache>/seed-cells/<version>`. The OpenCode binary check is `<bin-root>/bin/<sha>/opencode` (`--bin-root`, default `results/opencode-src`). The loaded-version check is the PR #156 strace `openat` of `node_modules/@ai-sdk/anthropic`. It runs only when that binary is present. The trace sets `HOME` to a directory under `<cache>/traces/` and points `$XDG_CACHE_HOME/opencode` at `<cache>/seed-cells/<version>`, not the caller's home. That seeded path is printed as `strace loaded-version cache: ...`.

On a machine that has the built binaries:

```bash
python3 -m thesis.ab.step8_pin_dry_run --cache /tmp/step8-pin-cache --bin-root <opencode-src>
```

`<opencode-src>` is the directory that contains `bin/<sha>/opencode`.

```
sides 594 ready 0 not-ready 594
  594 opencode binary missing (loaded-version check skipped; no binary to strace)
monorepo sides 6 ready 0 scorable 0
  51062 with    328f74c2 @opencode/ai@2.0.29 tree 0081539dc8aa; not ready: opencode binary missing at results/opencode-src/bin/328f74c2131ad700eebfa2f4b5ee64fe2cde78e2/opencode; scorable=no
  51062 without 32b1a1bf @opencode/ai@2.0.29 tree 0081539dc8aa; not ready: opencode binary missing at results/opencode-src/bin/32b1a1bf85ed1b9e57438c248463daea0b25a94f/opencode; scorable=no
  53166 with    0cb43477 @opencode/ai@2.0.27 tree 9022f537f155; not ready: opencode binary missing at results/opencode-src/bin/0cb434775c6bb1bda185976267f6bb7b26f9d98e/opencode; scorable=no
  53166 without bcf23b67 @opencode/ai@2.0.27 tree 9022f537f155; not ready: opencode binary missing at results/opencode-src/bin/bcf23b6775c79a429b1511b255d6d88ab0248d4a/opencode; scorable=no
  55613 with    ae8d59f8 @opencode/ai@2.0.29 tree 0081539dc8aa; not ready: opencode binary missing at results/opencode-src/bin/ae8d59f8b56c8034623d36ec514f9d9d4dc7cd5a/opencode; scorable=no
  55613 without 7ced591c @opencode/ai@2.0.29 tree 0081539dc8aa; not ready: opencode binary missing at results/opencode-src/bin/7ced591c3cc5094529befd23806d33b92e1167e0/opencode; scorable=no
```

Cache seeded for: `2.0.0`, `2.0.0-beta.11`, `3.0.64`, `3.0.71`.

Not ready because the OpenCode binaries for these SHAs are not built in this checkout. For pinned sides the pin resolved and the cache holds that version, so the remaining gap is the binary. Per-side paths are in `dry-run.csv`.

## Post-monorepo sides (51062, 53166, 55613)

These six sides have no `packages/opencode`. They are `provider_mode=bundled`. The CLI builds from `packages/cli`, and the Anthropic provider is OpenCode's own `packages/ai` (`@opencode/ai`), compiled into the binary. `bun.lock` has no `@ai-sdk/anthropic`, so nothing is pinned or seeded. `pins.csv` and `provider_pins.json` are unchanged. `bundled_provider` is the `@opencode/ai` version and the git tree id of `packages/ai/src`; both sides of each PR must match. When a binary is present, the strace check passes if the binary opens no `node_modules/@ai-sdk/anthropic` (`loaded_source=bundled`).

A monorepo binary is used only after `monorepo-builds.csv` shows a passed control step (three existing step-8 builds rebuilt, each matching its existing build's `opencode --version` and loaded provider) and a build record whose binary sha256 matches the binary on disk. Otherwise the side is not ready.

A monorepo side is `scorable=yes` only when it is ready and `monorepo-smoke.csv` shows its smoke cell loaded the bundled provider with zero provider faults and `score_match=true`: the smoke cell's scoring call equals the box's scoring call for that side as recorded on main. Missing box data is `score_match=false`.

```bash
python3 -m thesis.ab.step8_monorepo_build --cache <opencode-src>
python3 -m thesis.ab.step8_pin_dry_run --monorepo-only --bin-root <opencode-src> --mirror <opencode-mirror>
python3 -m thesis.ab.step8_monorepo_smoke --cache <opencode-src> --out results/step8-monorepo-smoke-<date> [--box-out <box run dir>]
```
