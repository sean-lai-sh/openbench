# Pin table rev2: bundled-SDK correction (2026-10-30, static only, no model calls)

This revises #214 (`results/pin-table-1030/pin-table.csv`, merged). **#214's files are not edited.** This directory adds a revised copy.

New columns in `pin-table.csv`: `bundled`, `bundled_version`, `pin_source_class`, `rerun_pin_rev2`, `rerun_pin_rule_rev2`, `bundled_evidence`. Per-build evidence is in `bundled-audit.json`.

Rule (Researcher, 2026-10-30): a build whose opencode binary bundles @ai-sdk/anthropic pins to the bundled version, with `pin_source_class=bundled`. A non-bundled build keeps its #214 pin.

Method: for both SHAs of each build I checked three things:
- `packages/opencode/package.json` and `bun.lock` (`opencode/@ai-sdk/anthropic`).
- Whether `provider.ts` puts `@ai-sdk/anthropic` in `BUNDLED_PROVIDERS`, either as a static import (13090, 13331, 5140) or a lazy `import()` (26821).
- The built binary in `~/h1/opencode-src/bin/<sha>/opencode`: the bun path `@ai-sdk+anthropic@X` via `obench/provider_embedded.py`, or a minified `var V="X"` used in the UA string `ai-sdk/anthropic/${V}`.

| Build | Bundled | Version | Rev2 pin (#214 rerun_pin) |
|---|---|---|---|
| 795 | no | – | 2.0.0-beta.4 (unchanged) |
| 913 | no | – | 2.0.0-beta.5 (unchanged) |
| 1109 | no | – | unchanged |
| 3052 | no | – | 2.0.25 (unchanged) |
| 4204 | no | – | unchanged |
| 5140 | yes | 2.0.50 | 2.0.50 (same value, class now bundled) |
| 13090 | yes | 2.0.58 | **2.0.58** (was 2.0.77) |
| 13331 | yes | 2.0.58 | **2.0.58** (was 2.0.77) |
| 26821 | yes | 3.0.71 | **3.0.71** (was 3.0.64) |
| 11731* | yes | 2.0.58 | **2.0.58** (was 2.0.77) |
| H1 50272* | yes | 3.0.111 | **3.0.111** (was 3.0.71) |

\* Not in the audit list. I checked these because the same rule applies.

**13331 deviation.** #214 recorded 13331's scored rows as `installed` 2.0.77. That was the npm cache version (the binary installs @latest into the cache), and it was never loaded. Both SHAs (ba54cee55e, 847e06f9e1) statically bundle 2.0.58 in `BUNDLED_PROVIDERS`, so the scored 13331 rows effectively ran 2.0.58. 13331 re-pins to 2.0.58 (bundled), and its gate must prove that 2.0.58 actually **loaded** (embedded), not just that it is installed in the cache. The same applies to 13090 and 11731 (2.0.58), 26821 (3.0.71; its scored rows' "3.0.64" is also the cache version only), and H1 50272 (3.0.111).

**Cost.** Cell counts are unchanged; only pin values change. No re-pricing: the #214 total stands.

**Known gap.** `provider_embedded.scan` returns '' for 26821 and c10134729d. Those binaries are minified code-split chunks with no bun source path, so a load proof for them needs a scanner fallback on `ai-sdk/anthropic/${V}` plus `var V="X"`. That is a code change for #207 and is not made here.
