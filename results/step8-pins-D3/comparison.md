# Step-8 D3 lockfile-pin validation gate (2026-10-26)

**Result: FAILED. 4 of 116 box_cache sides match; 112 disagree. Per D3 rule 2, no lockfile pins were added and no batch launches.**

Rule (thesis/ab/derive_lockfile_pins.py): the version bun locked for the provider package's own dependency, i.e. `packages/opencode` must declare `@ai-sdk/anthropic` and its resolved entry is read from `bun.lock` via `git show <sha>:bun.lock`. Zero or >1 version = unpinnable.

Why it fails: in most builds `packages/opencode` does not declare `@ai-sdk/anthropic` at all; provider.ts installs it at runtime with `BunProc.install(pkg, "latest")` (or a beta alias), so the box_cache version is the npm dist-tag on the day the box ran, not anything in the lockfile. Where some other workspace (e.g. `cloud/function`) locks a version, it agrees with box_cache on 54 sides only by coincidence (column `any_workspace_versions`), and disagrees on the rest (e.g. 1.2.12 locked vs 2.0.0-beta.11 cached).

Reproduce: `python3 thesis/ab/derive_lockfile_pins.py validate --mirror <opencode mirror> --out-dir results/step8-pins-D3` (exit 1).

| box_cache | lockfile (provider pkg) | sides |
|---|---|---|
| 2.0.0 | unpinnable | 67 |
| 2.0.0-beta.11 | 1.2.12 | 16 |
| 2.0.0-beta.13 | 1.2.12 | 9 |
| 3.0.64 | 3.0.71 | 8 |
| 2.0.0 | 1.2.12 | 6 |
| 1.2.12 | 1.2.12 | 4 |
| 2.0.0 | 2.0.50 | 2 |
| 3.0.64 | 3.0.67 | 2 |
| 3.0.71 | 3.0.82 | 2 |

Full per-side table: comparison.csv (sha, side, pr, box_cache, lockfile, match, note, any_workspace_versions).
