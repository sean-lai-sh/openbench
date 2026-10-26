# Step-8 amendment M1, deviation note D3: pins for builds the box never ran (2026-10-26)

Applies to: M1 (#137), D1 (#140), D2 (#141), and the pin file from #143. Covers F03-2 and every later step-8 batch (F04 to F16).

## Problem
provider_pins.json (#143) pins only the builds the box ran, plus F03-1. The remaining step-8 builds have no box_cache pin.

## Ruling
1. A build with no box_cache pin takes its `@ai-sdk/anthropic` version from the build's own lockfile in its VM worktree, recorded as pin_source = `lockfile`. A flat F03-era default (2.0.0) is not used.
2. Validation before first use: for every build that already has a box_cache pin, derive the lockfile version the same way and compare. The lockfile rule may be used only if it matches box_cache on every one of those builds. Commit the comparison table with the pins PR. If any build disagrees, stop and review before launch.
3. If a build's lockfile has no `@ai-sdk/anthropic` entry, or the entry can't be resolved to a single exact version, that side is not pinned by guess. The queue holds it, and it's reviewed.
4. The fail-closed rule from #143 still applies. A cell whose resolved version differs from its pin aborts before its first request and is recorded as infra (`provider_pin_mismatch`).
5. The derivation is a committed script, and it is rerun to reproduce the pins file.
