# Step-8 amendment M1, deviation note D5: reading of D4's gate, and remaining scope (2026-10-26)

Records how D4's validation gate (b) was read and settles the remaining step-8 scope (F03-2 through F16, PR 1443, and the post-monorepo PRs). Sean delegated this decision to the team on 2026-10-26. All data is kept.

## 1. Reading of D4 check (b)
D4 says "every miss is a version that no step-8 cell has failed on." This is read as provider faults only (chunk, transport and provider errors), not task failures. That was the intended meaning, but D4 worded it badly. It is recorded here as a disclosed deviation, not a silent reinterpretation.

Under this reading D4 passes:
- (b) Leave-one-out agreement is 98.3% and 97.4%. Every miss version, and 2.0.0, has zero provider faults. The only chunk faults were on 4.0.88 (9 faults, per #153 `6779b625`, confirmed in #154 `884808d7`).
- (a) Within-PR check: 56 of 57 PRs had both sides resolve the same version. The exception is PR 1443 (beta.13 vs beta.11).

## 2. Pins for F03-2 through F16
These use nearest-box-build pins per D4: pin_source = `nearest_box_build`, with the source build sha in the `pin_from` column.

## 3. PR 1443
Rerun with both sides on one version (about $5–6). The original mixed-version result is kept, labeled, and superseded for analysis.

## 4. Post-monorepo PRs 51062, 53166, 55613
These are built at `ae8d59f8`, have no `@ai-sdk` dependency, and cover 6 sides. They run with a provider-free runner and preflight change in a separate PR. They are scored only if a smoke test shows zero provider faults and the scoring call matches the box's on a shared PR. Otherwise they are dropped and reported as excluded.

## 5. Loaded-version logging
Every remaining cell logs the `@ai-sdk/anthropic` version it actually loaded (runner PR in flight). A mismatch with the pin fails closed as `provider_pin_mismatch`.

## 6. Launch gate
F03-2 launches only after the Researcher signs off on the pins PR dry run, which must show every side ready.
