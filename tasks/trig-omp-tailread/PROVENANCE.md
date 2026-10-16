# Provenance

- Source: re-authored 2026-10-16 for the thesis Oh My Pi A/B stage (the original was lost in the box restore).
- Trigger for OMP row 23 (2e6d96d3 vs 0d00f015): read selectors accept open-ended `N-` ("`301-` is shorthand for 'from 301 onward'"). The parent's `LINE_RANGE_RE` requires an end, and `N-` throws "Invalid range". Confirmed in the path-utils.ts and read.ts diffs.
- The 392-line log has its one error at line 391, so reading "from about line 380 on" is the natural move. The instruction doesn't say how to read the log (unforced).
- Decoy: `[test] jobs = 32` is legal (the README says the test runner allows up to 64) and must stay.
- Oracle: `[build] jobs` is an int in 1..8, and target, cache_dir, test jobs and timeout are unchanged.
