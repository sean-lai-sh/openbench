# Detectors: trig-omp-tailread (row 23) - SMOKE ONLY

- **Open-ended range read (primary):** `read` calls on logs/build.log with a selector of the form `:N-` (e.g. `:380-`). On the parent build this is a ToolError ("Invalid range N-0: end must be >= start"); on merge it reads to EOF. Per run: count of `:N-` selectors, count of range errors, and the selector used on the retry (bare `:N`, `:N-M`, or a bash `tail`).
- **Other tail strategies:** bash `tail`, `:-N` tail selectors, full read. Count per run.
- SMOKE ONLY: the model may never choose `N-`, since the old read.md doesn't document it. Use this task to check whether the trigger fires at all before screening. Exercised = ≥1 `:N-` selector.
