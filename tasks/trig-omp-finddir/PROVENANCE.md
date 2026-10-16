# Provenance

- Source: re-authored 2026-10-16 for the thesis Oh My Pi A/B stage (the original was lost in the box restore).
- Trigger for OMP row 25 (c31daf08 vs 8a32eceb): "find returns matching directories too, with a '/' suffix". Confirmed in find.md (`Finds files and directories`; example `{"paths": ["**/tests"]}`) and find.ts (the `fileType: File` filter was removed).
- The golden dir is 5 levels deep and its location isn't given, so the natural first step is to look for the directory. Nothing tells the model which tool to use (unforced).
- Oracle: empty_cart.json has the exact JSON, sits only in the golden dir, has a manifest entry in `name | description` form, and the existing entries are kept.
