# Build-date @ai-sdk/anthropic pins for H1/H2 OpenCode builds (2026-10-30, read-only, no model calls)

Files: `pin-table.csv` (one row per run/model/PR/arm group), `builds.json` (per build), `pintab.py` (generator, run on thesis-h1-cpu).
Mirror `~/h1/opencode-src/mirror` (origin anomalyco/opencode) fetched 2026-10-30. **Gaps: none.** All 24 builds resolved.
npm time data: registry metadata for @ai-sdk/anthropic, fetched 2026-10-30.

Researcher's pin rules (2026-10-30):
- **lockfile**: the build declares @ai-sdk/anthropic in packages/opencode/package.json (bundled provider). The pin is OpenCode's own bun.lock entry (`opencode/@ai-sdk/anthropic`, else the hoisted entry it resolves to). packages/console/function's entry is never used.
- **latest_at_build**: provider.ts runs `BunProc.install(pkg, "latest")` at runtime. The pin is the newest stable version published before the commit whose `@ai-sdk/provider` matches the build's `ai`. The July 2025 builds install the `beta` tag and no compatible stable existed then, so they get the newest compatible prerelease.
- Scored rows are not rerun. The `installed` column records what they actually ran.

| Builds (PR arms) | Commit dates | ai | Rule | Current pin | **Build-date pin** (published) | Scored rows: installed |
|---|---|---|---|---|---|---|
| 795 | 2025-07-09 | 5.0.0-beta.7 | latest_at_build (beta tag) | 2.0.0-beta.11 | **2.0.0-beta.4** (07-07) | beta.11 ×180 |
| 913 | 2025-07-12 | 5.0.0-beta.7 | latest_at_build (beta tag) | 2.0.0-beta.11 | **2.0.0-beta.5** (07-10) | beta.11 ×360 |
| 1109 | 2025-07-17 | 5.0.0-beta.21 | latest_at_build (beta tag) | 2.0.0-beta.11 | **2.0.0-beta.7** (07-17) | beta.11 ×180 |
| 2533 | 2025-09-10 | 5.0.8 | latest_at_build | 2.0.0 | **2.0.15** (09-09) | 2.0.0 ×180 |
| 3052 | 2025-10-09 | 5.0.8 | latest_at_build | 2.0.0 | **2.0.25** (10-09) | 2.0.0 ×180 (Sonnet; Opus arm unscored/rerun) |
| 4204 | 2025-11-18/19 | 5.0.8 | latest_at_build | 2.0.0 | **2.0.45** (11-18) | 2.0.0 ×180 |
| 5140 | 2025-12-06/07 | 5.0.97 | lockfile | 2.0.0 | **2.0.50** (11-27) | 2.0.0 ×180 |
| 11731, 13090, 13331 | 2026-02-01..12 | 5.0.124 | lockfile | 2.0.77 | **2.0.58** (01-30) | 2.0.77 ×630 |
| 26821 | 2026-05-15/16 | 6.0.168 | lockfile | 3.0.64 | **3.0.71** (04-16) | 3.0.64 ×360 |
| H1 50272 (A/A) | 2026-09-20 | 6.0.168 | lockfile | 3.0.71 | **3.0.111** (08-14) | 3.0.71 ×42 |

**The pin changes for every group.** 1,547 of the 2,479 scored rows ran on a version other than the build-date pin. They are not rerun.

## Total (one number)
- Drift reruns, now with build-date pins: the env-rerun cell set (`env-rerun-total.md`: checker-timeout cells, the full H2 arms Sonnet 795/913, Opus 913, Opus/Sonnet 3052, Opus 5140). That is 1,112 cells, priced at each cell's original `requests_cost_usd`: **$280.61**.
- Gate cells, one per distinct pin those reruns use: 8 pins (beta.4, beta.5, beta.7, 2.0.25, 2.0.45, 2.0.50, 2.0.58, 3.0.71) × $0.35–0.40 = **$2.80–3.20**.
- **Total $283.41–283.81**, plus $0.35 already spent = **$283.76–284.16, against the $300 stop**.
- 2.0.15 (2533) and 3.0.111 (H1) have no rerun cells. Gating them too would add $0.70–0.80.
