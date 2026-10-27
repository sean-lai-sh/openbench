# Step-8 pin dry run

No model calls and no GCP. Each F03-2..F16 side and both sides of `rerun-1443.json` were loaded. Pins were resolved from `provider_pins.json` (the 1443 rerun uses the single version in that config). The shared cache was seeded once per version with `bun add --exact` under `<cache>/seed-cells/<version>`. The OpenCode binary check is `<bin-root>/bin/<sha>/opencode` (`--bin-root`, default `results/opencode-src`). The loaded-version check is the PR #156 strace `openat` of `node_modules/@ai-sdk/anthropic`. It runs only when that binary is present. The trace sets `HOME` to a directory under `<cache>/traces/` and points `$XDG_CACHE_HOME/opencode` at `<cache>/seed-cells/<version>`, not the caller's home. That seeded path is printed as `strace loaded-version cache: ...`.

On a machine that has the built binaries:

```bash
python3 -m thesis.ab.step8_pin_dry_run --cache /tmp/step8-pin-cache --bin-root <opencode-src>
```

`<opencode-src>` is the directory that contains `bin/<sha>/opencode`.

```
sides 594 ready 0 not-ready 594
  588 opencode binary missing (loaded-version check skipped; no binary to strace)
  6 deferred post-monorepo; not pinned and not seeded
```

Cache seeded for: `2.0.0`, `2.0.0-beta.11`, `3.0.64`, `3.0.71`.

Not ready because the OpenCode binaries for these SHAs are not built in this checkout. The pin resolved and the cache holds that version, so the remaining gap is the binary. Deferred rows (51062, 53166, 55613) were not pinned and were not seeded. Per-side paths are in `dry-run.csv`.
