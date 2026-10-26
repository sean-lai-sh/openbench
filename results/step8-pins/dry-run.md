# Step-8 pin dry run

No model calls and no GCP. Each F03-2..F16 side and both sides of `rerun-1443.json` were loaded. Pins were resolved from `provider_pins.json` (the 1443 rerun uses the single version in that config). The shared cache was seeded once per version with `bun add --exact`. The OpenCode binary check is `results/opencode-src/bin/<sha>/opencode`. The loaded-version check is the PR #156 strace `openat` of `node_modules/@ai-sdk/anthropic`, and it runs only when that binary is present.

```
sides 594 ready 0 not-ready 594
  588 opencode binary missing (loaded-version check skipped; no binary to strace)
  6 deferred post-monorepo; not pinned and not seeded
```

Cache seeded for: `2.0.0`, `2.0.0-beta.11`, `3.0.64`, `3.0.71`.

Not ready because the OpenCode binaries for these SHAs are not built in this checkout. The pin resolved and the cache holds that version, so the remaining gap is the binary. Deferred rows (51062, 53166, 55613) were not pinned and were not seeded. Per-side paths are in `dry-run.csv`.
