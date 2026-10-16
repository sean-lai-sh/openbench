# Provenance

- Source: re-authored 2026-10-16 for the thesis Oh My Pi A/B stage (the original was lost in the box restore).
- Trigger for OMP row 40 (6b620e56 vs da94b644): directory reads switch from a trailing limit notice to an inline `… N more` marker. read.md now says "Child dirs cap at 12 entries (`… N more` marker) — read the sub-path to expand". Confirmed in the read.ts diff, which removes `resultBuilder.limits({ resultLimit: 1 })` for truncated trees.
- `codecs_pkg/plugins/` holds 17 codec modules plus `__init__.py` (18 children, over the 12-entry cap). `zstd.py` sorts last, so it lands behind the cap. The task never names the directory structure or tells the model to list anything (unforced).
- Oracle: the registry loads all 17 plugin modules, including zstd, and no plugin module was added or removed.
