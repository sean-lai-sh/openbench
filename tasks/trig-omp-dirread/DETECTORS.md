# Detectors: trig-omp-dirread (row 40)

- **Directory read of a capped child (primary):** `read` calls on `.` or `codecs_pkg` (directory paths). `codecs_pkg/plugins/` has 18 entries (>12), so a read of a parent shows it capped: an inline `… N more` marker on merge, a trailing limit notice on parent. Record per run whether a directory read showed the capped `plugins/` listing.
- **Follow-up:** after a capped listing, did the model read the sub-path `codecs_pkg/plugins` (the merge prompt says "read the sub-path to expand"), use bash `ls`, or neither? Count per run, plus tool calls between the capped read and the fix.
- **Misses:** runs where the model never sees `zstd.py` in any listing (decided from the registry name alone). These count as not exercised.
- Exercised = ≥1 directory `read` whose result was capped.
