# Step-8 amendment M1, deviation note D4: pins by nearest box build (2026-10-26)

Replaces D3's lockfile rule (#149), which failed its own validation gate (#148): only 4 of 116 box_cache sides matched. Covers F03-2 through F16.

## Why the lockfile failed
In most builds provider.ts installs `@ai-sdk/anthropic@latest` at run time, so the version a box cell cached depended on when and where it ran, not on the build's lockfile.

## Rule
1. Both sides of a PR get the same provider version. The point of this is that the provider version is never part of the with/without difference.
2. A build with no box_cache pin takes the box_cache version of the box-run build nearest to it in OpenCode commit history (by first-parent commit order, ties to the earlier one). This is recorded as pin_source = `nearest_box_build`, and the source build sha goes in a new `pin_from` column.
3. Before first use, two validation checks must pass.
   (a) Within-PR check: in the existing box data, how many PRs had both sides resolve the same version? Report the count. Any PR where the sides differed is listed for review.
   (b) Leave-one-out check: predict each of the 116 box_cache sides from its nearest other box-run build, and report the agreement rate. The rule may be used only if agreement is at least 95% and every miss is a version that no step-8 cell has failed on.
   If either check fails, stop and take it to Sean before any spend.
4. A side whose build lacks packages/opencode (for example F16-2, 55613 at ae8d59f8) is not run under this rule. It is listed with how the box handled it, and reviewed.
5. The fail-closed rule from #143 still applies, the derivation is a committed script, and the comparison tables are committed with the pins PR.
