# Step-8 amendment M1, deviation note D2: VM package pinning (2026-10-26)

Applies to: M1 (briefs/step8-amendment-machine-move-2026-10-25.md, merged in #137 as 6dee350b) and D1 (#140, a9c57d85).

## What happened
On the thesis-h1-cpu VM, some step-8 cells in F03-1 died within about 10 s with `Unhandled chunk type: custom` and were filed as infra. Across all of the box's step-8 cells, this error appears 0 times. The working hypothesis (not yet confirmed) is that the VM resolves newer `@ai-sdk/*` packages than the box did, and that older OpenCode builds can't handle a new stream chunk type. The infra failures were uneven across sides (3185: 3 infra on with-side only), and they triggered early stops on 3185 and 3192.

## Ruling
1. The first F03-1 run on the VM is committed as quarantined data, kept, and not scored or pooled.
2. The VM uses the box's exact package set (lockfile or node_modules, with the provider pinned). Under that setup, F03-1 reruns in full.
3. The M1 A/A check validated one stock OpenCode build. It did not cover dependency drift in older PR builds. Pinning removes that drift. A new A/A check is needed only if the pinned lockfile changes OpenCode's own provider version from the one the A/A check used.
4. The gate to continue past F03-1 on the pinned VM has two parts. (a) The rerun has zero `Unhandled chunk type` errors. (b) Every F03-1 PR that the box also ran falls on the same side of the scoring rules as on the box: token effect or none, and the same pass-rate call. If either part fails, the run stops for review.
5. Every cell records the lockfile sha256 alongside the machine and runner sha. Runner sha may be backfilled from `driver.log` (`runner=980e71b618`), but only if the backfill script is committed with the data.
